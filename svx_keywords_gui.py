#!/usr/bin/env python3

"""svx_keywords_gui.py
A simple tkinter front end for svx_keywords.py (survex keyword / grep search).

It builds the same command line you would type in a terminal, runs
svx_keywords.py in a subprocess, and streams the (colourised) output into
a window.  svx_keywords.py itself is not modified.

Usage:   python3 svx_keywords_gui.py [top_level_file.svx]

Put this file in the same folder as svx_keywords.py - the GUI always looks
for it right next to itself.

On Debian/Ubuntu tkinter may need:   sudo apt install python3-tk
For spreadsheet output you need:     pip install pandas openpyxl   (.xlsx)
                                     pip install pandas odfpy      (.ods)

Matching lines are also parsed into a sortable, filterable results table
(click a column heading to sort, type in the filter box to narrow it down),
and double-clicking a row opens that file at the matched line in an editor
of your choice (see the "Editor" field above the table).
"""

import importlib.util
import os
import queue
import re
import shlex
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

SCRIPT_NAME = 'svx_keywords.py'

# ANSI colour handling (svx_keywords.py emits these when -c is given)
ANSI_RE = re.compile(r'\x1b\[([0-9;]*)m')
ANSI_COLOURS = {'31': 'red', '32': 'green', '33': 'yellow',
                '34': 'blue', '35': 'purple', '36': 'cyan'}
TAG_COLOURS = {'red': '#c0392b', 'green': '#1e8449', 'yellow': '#9a7d0a',
               'blue': '#1f4fd8', 'purple': '#8e44ad', 'cyan': '#117a8b',
               'error': '#c0392b'}

# svx_keywords.py prints matching lines as  path:line:context:text.  This
# pattern splits a plain (ANSI-stripped) output line back into its fields
# for the table.  The path and context fields are assumed not to contain a
# colon themselves, which holds for normal file paths and *begin block names.
ROW_PATTERN = re.compile(r'^(?P<file>.+?):(?P<line>\d+):(?P<context>[^:]*):(?P<text>.*)$')

# (executable, command template) pairs, tried in this order to guess a
# sensible default for the "open result in editor" field. {file} and {line}
# are substituted before the command is split and run.
EDITOR_GUESSES = [
    ('code', 'code -g "{file}:{line}"'),
    ('codium', 'codium -g "{file}:{line}"'),
    ('subl', 'subl "{file}:{line}"'),
    ('gedit', 'gedit +{line} "{file}"'),
    ('kate', 'kate -l {line} "{file}"'),
    ('gvim', 'gvim +{line} "{file}"'),
    ('emacs', 'emacs +{line} "{file}"'),
]


def guess_editor_command():
    '''Best-effort default for the editor command field'''
    for exe, template in EDITOR_GUESSES:
        if shutil.which(exe):
            return template
    editor = os.environ.get('VISUAL') or os.environ.get('EDITOR')
    if editor:
        return f'{editor} +{{line}} "{{file}}"'
    return 'xdg-open "{file}"'  # can't jump to a line, but opens something


class Tooltip:
    '''Minimal hover tooltip'''

    def __init__(self, widget, text):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind('<Enter>', self.show, add='+')
        widget.bind('<Leave>', self.hide, add='+')

    def show(self, _event=None):
        if self.tip:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f'+{x}+{y}')
        tk.Label(tw, text=self.text, background='#ffffe0', relief='solid',
                 borderwidth=1, padx=4, pady=2, justify='left',
                 wraplength=380).pack()

    def hide(self, _event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class App(ttk.Frame):

    def __init__(self, master, initial_file=''):
        super().__init__(master, padding=8)
        self.master = master
        self.proc = None
        self.queue = queue.Queue()
        self.ansi_tag = None
        self.line_count = 0
        self.grep_mode_running = False

        # --- variables (names follow the command line options) ---
        self.script = str(Path(__file__).resolve().parent / SCRIPT_NAME)  # fixed, alongside this file
        self.svx = tk.StringVar(value=initial_file)
        self.keywords = tk.StringVar(value='include,begin,end')  # -k, pre-filled with the defaults
        self.no_ignore_case = tk.BooleanVar()      # -n
        self.totals = tk.BooleanVar()              # -t
        self.summarize = tk.BooleanVar()           # -s
        self.do_output = tk.BooleanVar()           # -o
        self.output = tk.StringVar()
        self.quiet = tk.BooleanVar()               # -q
        self.grep = tk.StringVar()                 # -g
        self.ignore_case = tk.BooleanVar()         # -i
        self.list_files = tk.BooleanVar()          # -l
        self.directories = tk.BooleanVar()         # -d
        self.status = tk.StringVar(value='Ready')
        self.preview = tk.StringVar()

        # --- results table state ---
        self.editor_cmd = tk.StringVar(value=guess_editor_command())  # {file} {line}
        self.filter_var = tk.StringVar()
        self.row_count_var = tk.StringVar(value='0 rows')
        self.rows = []                 # every parsed row, in arrival order
        self.sort_col = None
        self.sort_reverse = False
        self.run_cwd = None            # working folder used for the last run
        self.run_table_eligible = False  # did the last run print per-line matches?
        self.headings = {'file': 'File', 'line': 'Line', 'context': 'Context', 'text': 'Text'}

        self.build_ui()

        watched = [self.svx, self.keywords, self.no_ignore_case, self.totals,
                   self.summarize, self.do_output, self.output, self.quiet,
                   self.grep, self.ignore_case, self.list_files, self.directories]
        for var in watched:
            var.trace_add('write', self.update_preview)
        self.notebook.bind('<<NotebookTabChanged>>', self.update_preview)
        self.filter_var.trace_add('write', lambda *_: self.refresh_table())
        self.update_preview()

    # ------------------------------------------------------------------
    # layout
    # ------------------------------------------------------------------

    def entry_row(self, parent, row, label, var, tip=None, hint=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', pady=2)
        entry = ttk.Entry(parent, textvariable=var)
        entry.grid(row=row, column=1, sticky='ew', padx=4, pady=2)
        if hint:
            ttk.Label(parent, text=hint, foreground='#666666').grid(
                row=row, column=2, sticky='w')
        if tip:
            Tooltip(entry, tip)
        return entry

    def check(self, parent, text, var, tip, row, col, span=1):
        cb = ttk.Checkbutton(parent, text=text, variable=var)
        cb.grid(row=row, column=col, columnspan=span, sticky='w', padx=(0, 12), pady=1)
        Tooltip(cb, tip)
        return cb

    def build_ui(self):
        self.pack(fill='both', expand=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(5, weight=1)

        # --- files ---
        f = ttk.LabelFrame(self, text='Files', padding=6)
        f.grid(row=0, column=0, sticky='ew')
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text='Top-level .svx file:').grid(row=0, column=0, sticky='w', pady=2)
        ttk.Entry(f, textvariable=self.svx).grid(row=0, column=1, sticky='ew', padx=4)
        ttk.Button(f, text='Browse…', command=self.browse_svx).grid(row=0, column=2)

        # --- search mode tabs ---
        self.notebook = nb = ttk.Notebook(self)
        nb.grid(row=1, column=0, sticky='ew', pady=(8, 0))

        kw = ttk.Frame(nb, padding=8)
        kw.columnconfigure(1, weight=1)
        nb.add(kw, text='Keyword search')
        self.entry_row(kw, 0, 'Keywords:', self.keywords,
                       '-k  Comma-separated, case insensitive. Pre-filled with the '
                       'defaults (include, begin, end) - edit freely to add or remove '
                       'any, e.g. include,begin,end,entrance,fix')
        opts = ttk.Frame(kw)
        opts.grid(row=1, column=0, columnspan=3, sticky='w', pady=(4, 0))
        self.check(opts, 'Totals per keyword', self.totals,
                   '-t  Print a count for each keyword instead of the matching lines.', 0, 0)
        self.check(opts, 'One-line summary', self.summarize,
                   '-s  Print a one-line summary instead of the matching lines.', 0, 1)
        self.check(opts, 'Preserve keyword case (spreadsheet)', self.no_ignore_case,
                   '-n  Keep the keyword as written in the source rather than '
                   'upper-casing it (affects spreadsheet output).', 0, 2)

        sp = ttk.LabelFrame(kw, text='Spreadsheet output', padding=6)
        sp.grid(row=2, column=0, columnspan=3, sticky='ew', pady=(8, 0))
        sp.columnconfigure(1, weight=1)
        self.check(sp, 'Write to spreadsheet:', self.do_output,
                   '-o  Write the results to a .xlsx or .ods file instead of '
                   'printing the matching lines.', 0, 0)
        ttk.Entry(sp, textvariable=self.output).grid(row=0, column=1, sticky='ew', padx=4)
        ttk.Button(sp, text='Save as…', command=self.browse_output).grid(row=0, column=2)
        self.check(sp, 'Quiet (only print errors)', self.quiet,
                   '-q  Suppress the summary messages when writing a spreadsheet.',
                   1, 0, span=2)

        gr = ttk.Frame(nb, padding=8)
        gr.columnconfigure(1, weight=1)
        nb.add(gr, text='Text search (grep)')
        self.entry_row(gr, 0, 'Pattern (regex):', self.grep,
                       '-g  A Python regular expression matched against every line '
                       'in the survex file tree.')
        self.check(gr, 'Ignore case', self.ignore_case,
                   '-i  Case-insensitive matching.', 1, 0, span=2)

        # --- display options (both modes) ---
        d = ttk.LabelFrame(self, text='Display options', padding=6)
        d.grid(row=2, column=0, sticky='ew', pady=(8, 0))
        self.check(d, 'List files visited', self.list_files,
                   '-l  Also report each file as it is opened.', 0, 0)
        self.check(d, 'Absolute paths', self.directories,
                   '-d  Show absolute file paths instead of relative ones.', 0, 1)

        # --- command preview ---
        p = ttk.Frame(self)
        p.grid(row=3, column=0, sticky='ew', pady=(8, 0))
        p.columnconfigure(1, weight=1)
        ttk.Label(p, text='Equivalent command:').grid(row=0, column=0, sticky='w')
        ttk.Entry(p, textvariable=self.preview, state='readonly').grid(
            row=0, column=1, sticky='ew', padx=4)
        Tooltip(p, 'This is what the GUI runs, from inside the .svx file\'s folder.')

        # --- buttons ---
        b = ttk.Frame(self)
        b.grid(row=4, column=0, sticky='ew', pady=8)
        self.run_btn = ttk.Button(b, text='Run', command=self.run)
        self.run_btn.pack(side='left')
        self.stop_btn = ttk.Button(b, text='Stop', command=self.stop, state='disabled')
        self.stop_btn.pack(side='left', padx=4)
        ttk.Button(b, text='Clear', command=self.clear).pack(side='left')
        ttk.Button(b, text='Copy', command=self.copy).pack(side='left', padx=4)
        ttk.Button(b, text='Save output…', command=self.save_output).pack(side='left')
        self.master.bind('<Control-Return>', lambda e: self.run())

        # --- results: a sortable/filterable table, and the raw text output ---
        self.results_notebook = rn = ttk.Notebook(self)
        rn.grid(row=5, column=0, sticky='nsew')

        # -- table tab --
        t = ttk.Frame(rn, padding=(0, 6, 0, 0))
        t.columnconfigure(0, weight=1)
        t.rowconfigure(1, weight=1)
        rn.add(t, text='Results table')

        tb = ttk.Frame(t)  # toolbar: filter box, editor command, open button
        tb.grid(row=0, column=0, sticky='ew', pady=(0, 4))
        tb.columnconfigure(1, weight=2)
        tb.columnconfigure(5, weight=3)
        ttk.Label(tb, text='Filter:').grid(row=0, column=0, sticky='w')
        filter_entry = ttk.Entry(tb, textvariable=self.filter_var)
        filter_entry.grid(row=0, column=1, sticky='ew', padx=(4, 12))
        Tooltip(filter_entry, 'Show only rows containing this text, in any column '
                '(case insensitive).')
        ttk.Label(tb, textvariable=self.row_count_var).grid(row=0, column=2, sticky='w')
        order_btn = ttk.Button(tb, text='Original order', command=self.restore_order)
        order_btn.grid(row=0, column=3, padx=(12, 0))
        Tooltip(order_btn, 'Undo any column sorting and show rows in the order '
                'they were found.')
        ttk.Label(tb, text='Open with:').grid(row=0, column=4, sticky='w', padx=(12, 0))
        editor_entry = ttk.Entry(tb, textvariable=self.editor_cmd)
        editor_entry.grid(row=0, column=5, sticky='ew', padx=4)
        Tooltip(editor_entry, 'Command used to open a double-clicked result. {file} and '
                '{line} are replaced with the matched file and line number.\n\nExamples:\n'
                '  code -g "{file}:{line}"     (VS Code)\n'
                '  gedit +{line} "{file}"      (gedit)\n'
                '  kate -l {line} "{file}"     (Kate)\n'
                '  subl "{file}:{line}"        (Sublime Text)\n'
                '  gvim +{line} "{file}"       (gVim)\n'
                '  emacs +{line} "{file}"      (Emacs)')
        ttk.Button(tb, text='Open', command=self.open_selected).grid(row=0, column=6)

        columns = ('file', 'line', 'context', 'text')
        self.tree = ttk.Treeview(t, columns=columns, show='headings', selectmode='browse')
        widths = {'file': 260, 'line': 55, 'context': 140, 'text': 380}
        anchors = {'line': 'e'}
        for col in columns:
            self.tree.heading(col, text=self.headings[col],
                              command=lambda c=col: self.sort_by(c))
            self.tree.column(col, width=widths[col], anchor=anchors.get(col, 'w'),
                             stretch=(col == 'text'))
        tys = ttk.Scrollbar(t, orient='vertical', command=self.tree.yview)
        txs = ttk.Scrollbar(t, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=tys.set, xscrollcommand=txs.set)
        self.tree.grid(row=1, column=0, sticky='nsew')
        tys.grid(row=1, column=1, sticky='ns')
        txs.grid(row=2, column=0, sticky='ew')
        self.tree.tag_configure('odd', background='#f4f4f4')
        self.tree.bind('<Double-1>', self.on_table_double_click)
        Tooltip(self.tree, 'Click a heading to sort. Double-click a row (or select it and '
                'press Open) to open the file in your editor at that line.')

        empty = ttk.Label(t, foreground='#666666', padding=(2, 6), justify='left',
                          text='The table fills in with matching lines from a keyword or '
                          'grep search.\n"Totals", "Summary" and spreadsheet-only runs '
                          "don't print individual lines, so the table stays empty for "
                          'those \u2014 check the raw output tab instead.')
        empty.grid(row=1, column=0, sticky='nw')
        self.empty_hint = empty
        self.empty_hint.lower(self.tree)  # tree covers the hint once rows arrive

        # -- raw output tab --
        o = ttk.Frame(rn)
        o.columnconfigure(0, weight=1)
        o.rowconfigure(0, weight=1)
        rn.add(o, text='Raw output')
        mono = tkfont.nametofont('TkFixedFont')
        self.text = tk.Text(o, wrap='none', height=18, font=mono, state='disabled',
                            background='#fbfbfb')
        ys = ttk.Scrollbar(o, orient='vertical', command=self.text.yview)
        xs = ttk.Scrollbar(o, orient='horizontal', command=self.text.xview)
        self.text.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.text.grid(row=0, column=0, sticky='nsew')
        ys.grid(row=0, column=1, sticky='ns')
        xs.grid(row=1, column=0, sticky='ew')
        for tag, colour in TAG_COLOURS.items():
            self.text.tag_configure(tag, foreground=colour)

        ttk.Label(self, textvariable=self.status, relief='sunken',
                  anchor='w', padding=(4, 2)).grid(row=6, column=0, sticky='ew', pady=(6, 0))

    # ------------------------------------------------------------------
    # file dialogs
    # ------------------------------------------------------------------

    def browse_svx(self):
        name = filedialog.askopenfilename(
            title='Choose the top-level survex file',
            filetypes=[('Survex files', '*.svx'), ('All files', '*')])
        if name:
            self.svx.set(name)

    def browse_output(self):
        name = filedialog.asksaveasfilename(
            title='Save spreadsheet as', defaultextension='.xlsx',
            filetypes=[('Excel workbook', '*.xlsx'), ('OpenDocument spreadsheet', '*.ods')])
        if name:
            self.output.set(name)
            self.do_output.set(True)

    # ------------------------------------------------------------------
    # command construction
    # ------------------------------------------------------------------

    def grep_mode(self):
        return self.notebook.index(self.notebook.select()) == 1

    def build_command(self):
        '''Return (argument list, working directory, svx file name).
        Raises ValueError if a required field is missing.'''
        svx = self.svx.get().strip()
        if not svx:
            raise ValueError('choose a top-level .svx file')
        svx_path = Path(svx).expanduser().absolute()

        args = []
        if self.grep_mode():
            pattern = self.grep.get()
            if not pattern:
                raise ValueError('enter a search pattern')
            args += ['-g', pattern]
            if self.ignore_case.get():
                args.append('-i')
        else:
            value = self.keywords.get().replace(' ', '').strip(',')
            if value:
                args += ['-k', value]
            for flag, var in (('-n', self.no_ignore_case), ('-t', self.totals),
                              ('-s', self.summarize)):
                if var.get():
                    args.append(flag)
            if self.do_output.get():
                out = self.output.get().strip()
                if not out:
                    raise ValueError('choose a spreadsheet file name')
                out = Path(out).expanduser().absolute()
                if out.suffix.lower() not in ('.xlsx', '.ods'):
                    out = out.with_suffix('.xlsx')
                args += ['-o', str(out)]
                if self.quiet.get():
                    args.append('-q')

        for flag, var in (('-l', self.list_files), ('-d', self.directories)):
            if var.get():
                args.append(flag)
        args += ['-x', '-c']  # always show survex context and colourise; the GUI renders both

        # Run inside the folder of the svx file, so relative paths in the
        # output are short and match what you'd see from the terminal there.
        return args, str(svx_path.parent), svx_path.name

    def update_preview(self, *_):
        try:
            args, cwd, name = self.build_command()
        except ValueError as err:
            self.preview.set(f'({err})')
            return
        script = Path(self.script).name
        self.preview.set(shlex.join(['python3', script] + args + [name]))

    # ------------------------------------------------------------------
    # running
    # ------------------------------------------------------------------

    def run(self):
        if self.proc:
            return
        try:
            args, cwd, name = self.build_command()
        except ValueError as err:
            messagebox.showerror('Cannot run', f'Please {err}.')
            return

        script = Path(self.script)
        if not script.is_file():
            messagebox.showerror('Cannot run', f'Cannot find {SCRIPT_NAME}.\n'
                                 'It should be in the same folder as this GUI script:\n'
                                 f'{script.parent}')
            return
        svx_path = Path(cwd, name)
        if not svx_path.exists() and not svx_path.with_suffix('.svx').exists():
            messagebox.showerror('Cannot run', f'File not found:\n{svx_path}')
            return
        if '-o' in args:
            out_path = args[args.index('-o') + 1]
            needed = 'odf' if out_path.endswith('.ods') else 'openpyxl'
            pip_name = 'odfpy' if needed == 'odf' else 'openpyxl'
            missing = [m for m, p in (('pandas', 'pandas'), (needed, pip_name))
                       if importlib.util.find_spec(m) is None]
            if missing:
                names = ' '.join('pandas' if m == 'pandas' else pip_name for m in missing)
                messagebox.showerror('Missing Python package',
                                     'Spreadsheet output needs extra packages.\n'
                                     f'Install with:\n\n    pip install {names}')
                return

        self.clear()
        self.grep_mode_running = self.grep_mode()
        self.run_cwd = cwd
        # keyword mode only prints per-line matches when totals/summarize/output
        # are all off (otherwise it just prints counts) - grep mode always does
        self.run_table_eligible = (self.grep_mode_running or
                                   not (self.totals.get() or self.summarize.get()
                                        or self.do_output.get()))
        self.results_notebook.select(0 if self.run_table_eligible else 1)
        env = dict(os.environ, PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8')
        cmd = [sys.executable, '-u', str(script.absolute())] + args + [name]
        try:
            self.proc = subprocess.Popen(cmd, cwd=cwd, env=env,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as err:
            messagebox.showerror('Cannot run', str(err))
            self.proc = None
            return

        self.set_running(True)
        self.status.set('Running…')
        proc = self.proc
        readers = [threading.Thread(target=self.reader, args=(proc.stdout, 'out'), daemon=True),
                   threading.Thread(target=self.reader, args=(proc.stderr, 'err'), daemon=True)]
        for t in readers:
            t.start()
        threading.Thread(target=self.waiter, args=(proc, readers), daemon=True).start()
        self.after(40, self.poll)

    def reader(self, pipe, kind):
        for raw in iter(pipe.readline, b''):
            self.queue.put((kind, raw.decode('utf-8', errors='replace')))
        pipe.close()

    def waiter(self, proc, readers):
        for t in readers:
            t.join()
        self.queue.put(('done', proc.wait()))

    def poll(self):
        '''Move queued output into the text widget (called from the Tk thread)'''
        finished = None
        for _ in range(2000):  # cap per tick so the window stays responsive
            try:
                kind, payload = self.queue.get_nowait()
            except queue.Empty:
                break
            if kind == 'done':
                finished = payload
                break
            self.append(payload, error=(kind == 'err'))
        self.text.see('end')
        if finished is not None:
            self.finish(finished)
        else:
            self.after(40, self.poll)

    def append(self, s, error=False):
        self.text.configure(state='normal')
        if error:
            self.text.insert('end', s, ('error',))
        else:
            self.ansi_tag = None  # each printed line resets its own colours
            pos = 0
            for m in ANSI_RE.finditer(s):
                if m.start() > pos:
                    self.text.insert('end', s[pos:m.start()],
                                     (self.ansi_tag,) if self.ansi_tag else ())
                for code in m.group(1).split(';'):
                    if code in ('', '0'):
                        self.ansi_tag = None
                    elif code in ANSI_COLOURS:
                        self.ansi_tag = ANSI_COLOURS[code]
                pos = m.end()
            if pos < len(s):
                self.text.insert('end', s[pos:], (self.ansi_tag,) if self.ansi_tag else ())
            self.line_count += 1
            if self.run_table_eligible:
                self.add_table_row(ANSI_RE.sub('', s))
        self.text.configure(state='disabled')

    # ------------------------------------------------------------------
    # results table
    # ------------------------------------------------------------------

    def add_table_row(self, plain_line):
        '''Parse one plain (ANSI-stripped) output line and add it to the table'''
        plain_line = plain_line.rstrip('\r\n')
        if not plain_line:
            return
        pattern = ROW_PATTERN
        m = pattern.match(plain_line)
        if not m:
            return  # a totals/summary line, or something else that doesn't fit the table
        fields = m.groupdict()
        row = {'file': fields['file'], 'line': fields['line'],
               'context': fields['context'], 'text': fields['text']}
        self.rows.append(row)
        if self.row_matches_filter(row):
            self.insert_row(row, len(self.rows) - 1)
        self.row_count_var.set(f'{len(self.tree.get_children())} of {len(self.rows)} rows')
        if len(self.rows) == 1:
            self.tree.lift(self.empty_hint)  # hide the placeholder once real rows exist

    def row_matches_filter(self, row):
        needle = self.filter_var.get().strip().lower()
        if not needle:
            return True
        haystack = f"{row['file']} {row['line']} {row['context']} {row['text']}".lower()
        return needle in haystack

    def insert_row(self, row, index):
        tag = 'odd' if index % 2 else ''
        self.tree.insert('', 'end', values=(row['file'], row['line'], row['context'],
                                             row['text']), tags=(tag,) if tag else ())

    def refresh_table(self):
        '''Rebuild the visible table from self.rows, applying the current filter and sort'''
        filtered = [(i, r) for i, r in enumerate(self.rows) if self.row_matches_filter(r)]
        if self.sort_col:
            def key(item):
                value = item[1][self.sort_col]
                if self.sort_col == 'line':
                    return (value == '', int(value) if value.isdigit() else 0)
                return value.lower()
            filtered.sort(key=key, reverse=self.sort_reverse)
        self.tree.delete(*self.tree.get_children())
        for display_index, (_, row) in enumerate(filtered):
            self.insert_row(row, display_index)
        self.row_count_var.set(f'{len(filtered)} of {len(self.rows)} rows')

    def sort_by(self, col):
        if self.sort_col == col:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_col, self.sort_reverse = col, False
        for c in ('file', 'line', 'context', 'text'):
            arrow = (' \u25bc' if self.sort_reverse else ' \u25b2') if c == col else ''
            self.tree.heading(c, text=self.headings[c] + arrow)
        self.refresh_table()

    def restore_order(self):
        '''Drop any column sort and show rows in the order they were found'''
        self.sort_col, self.sort_reverse = None, False
        for c in ('file', 'line', 'context', 'text'):
            self.tree.heading(c, text=self.headings[c])
        self.refresh_table()

    def clear_table(self):
        self.tree.delete(*self.tree.get_children())
        self.rows = []
        self.sort_col, self.sort_reverse = None, False
        for c in ('file', 'line', 'context', 'text'):
            self.tree.heading(c, text=self.headings[c])
        self.row_count_var.set('0 rows')
        self.tree.lower(self.empty_hint)

    def selected_row_values(self):
        selection = self.tree.selection()
        if not selection:
            return None
        return self.tree.item(selection[0], 'values')  # (file, line, context, text)

    def on_table_double_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        self.tree.selection_set(item)
        values = self.tree.item(item, 'values')
        self.open_in_editor(values[0], values[1])

    def open_selected(self):
        values = self.selected_row_values()
        if not values:
            self.status.set('Select a row in the table first')
            return
        self.open_in_editor(values[0], values[1])

    def build_editor_command(self, file_field, line_field):
        '''Work out the absolute path and the editor command to run for a table row.
        Raises ValueError with a user-facing message if that isn't possible.'''
        if not file_field:
            raise ValueError('that row has no file recorded')
        path = Path(file_field)
        if not path.is_absolute():
            path = Path(self.run_cwd or Path(self.svx.get()).expanduser().absolute().parent,
                        file_field)
        if not path.exists():
            raise ValueError(f"can't find {path}")
        template = self.editor_cmd.get().strip()
        if not template:
            raise ValueError('set an editor command first (top right of the table)')
        line = line_field if (line_field and str(line_field).isdigit()
                              and int(line_field) > 0) else '1'
        command = template.replace('{file}', str(path)).replace('{line}', str(line))
        try:
            args = shlex.split(command)
        except ValueError as err:
            raise ValueError(f'editor command is not valid: {err}') from err
        if not args:
            raise ValueError('editor command is empty')
        return path, args

    def open_in_editor(self, file_field, line_field):
        try:
            path, args = self.build_editor_command(file_field, line_field)
        except ValueError as err:
            messagebox.showerror('Cannot open editor', str(err).capitalize())
            return
        try:
            subprocess.Popen(args)
        except OSError as err:
            messagebox.showerror('Cannot open editor',
                                 f"Couldn't run '{args[0]}': {err}")
            return
        self.status.set(f'Opened {path}' + (f' at line {line_field}' if line_field else ''))

    def finish(self, rc):
        self.proc = None
        self.set_running(False)
        n = self.line_count
        if rc == 0:
            self.status.set(f'Finished ({n} lines of output)')
        elif rc == 1 and self.grep_mode_running:
            self.status.set('Finished: no matches found')
        elif rc < 0:
            self.status.set('Stopped')
        else:
            self.status.set(f'Script exited with an error (code {rc}), see output above')

    def stop(self):
        if self.proc:
            self.proc.terminate()

    def set_running(self, running):
        self.run_btn.configure(state='disabled' if running else 'normal')
        self.stop_btn.configure(state='normal' if running else 'disabled')

    # ------------------------------------------------------------------
    # output helpers
    # ------------------------------------------------------------------

    def clear(self):
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        self.text.configure(state='disabled')
        self.line_count = 0
        self.clear_table()

    def copy(self):
        try:
            selected = self.text.get('sel.first', 'sel.last')
        except tk.TclError:
            selected = self.text.get('1.0', 'end-1c')
        self.clipboard_clear()
        self.clipboard_append(selected)
        self.status.set('Copied to clipboard')

    def save_output(self):
        name = filedialog.asksaveasfilename(
            title='Save output as text', defaultextension='.txt',
            filetypes=[('Text files', '*.txt'), ('All files', '*')])
        if name:
            Path(name).write_text(self.text.get('1.0', 'end-1c'), encoding='utf-8')
            self.status.set(f'Output saved to {name}')

    def on_close(self):
        if self.proc:
            self.proc.terminate()
        self.master.destroy()


def main():
    root = tk.Tk()
    root.title('Survex keyword search')
    style = ttk.Style()
    if 'clam' in style.theme_names():
        style.theme_use('clam')
    app = App(root, initial_file=sys.argv[1] if len(sys.argv) > 1 else '')
    root.minsize(780, 680)
    root.protocol('WM_DELETE_WINDOW', app.on_close)
    root.mainloop()


if __name__ == '__main__':
    main()
