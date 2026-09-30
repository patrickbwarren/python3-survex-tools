#!/usr/bin/env python3

"""svx_keywords.py
Python module and wrapper code for extracting survex keywords
from a source data file tree.

For usage see README.md.

Copyright (c) 2023 Patrick B Warren

Email: patrickbwarren@gmail.com

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see
<http://www.gnu.org/licenses/>.

"""

import re, sys
from pathlib import Path

def svx_encoding(p):
    '''Try to figure out the character encoding that works for a file'''
    success = False
    for encoding in ['utf-8', 'iso-8859-1']: # list of options to try
        with p.open('r', encoding=encoding) as fp:
            try:
                fp.readlines() # we don't need to capture the output here
            except UnicodeDecodeError:
                pass
            else: # if we didn't fail, we found something that works
                success = True
                break
    if not success:
        raise UnicodeDecodeError(f'Couldnt determine the character encoding for {p}')
    return encoding

# In the following, hook can be a function which accepts the path p
# and the context, and returns a line of text (typically, a report).
# The returned value is recorded as a postscript either in the
# SvxReader class for the initial file open, or in the SvxRecord class
# for subsequent file openings.  The wrapper code below checks for
# such a postscript and prints it out at the appropriate time.  This
# means the file openings are reported _after_ the relevant *include
# statement.  If the file is not found a null fp is returned, to be
# handled gracefully by the calling routine.

def svx_open(p, hook=None, context=[]):
    '''open a survex file and reset line counter'''
    if not p.exists():
        return None, 0, None, ''
    encoding = svx_encoding(p)
    fp = p.open('r', encoding=encoding)
    postscript = hook(p, context) if hook else ''
    line_number = 0
    return fp, line_number, encoding, postscript

def trace_hook(p, context, status='entered'):
    '''hook for tracing which files are being visited'''
    path = str(p.absolute()) if args.directories else str(p)
    context = '.'.join(context) if args.context else ''
    if args.color:
        context = f'{BLUE}{context}{CYAN}' if context else ''
        if args.omit_linen:
            postscript = f'{PURPLE}{path}{CYAN}:{BLUE}{context}:{RED}{status}{NC}'
        else:
            postscript = f'{PURPLE}{path}{CYAN}:{GREEN}0{CYAN}:{BLUE}{context}:{RED}{status}{NC}'
    else:
        if args.omit_linen:
            postscript = f'{path}:{context}:{status}'
        else:
            postscript = f'{path}:0:{context}:{status}'
    return postscript

def svx_readline(fp, line_number):
    '''read a line from the survex file and increment line counter'''
    return fp.readline(), line_number+1

def extract_keyword_arguments(clean, keywords, keyword_char):
    '''Extract a keyword and arguments from a cleaned up line'''
    if clean and clean[0] == keyword_char: # detect keyword by presence of keyword character
        clean_list = clean[1:].split() # drop the keyword char and split on white space
        for keyword in keywords: # identify the keyword from the list of possible ones
            if clean_list[0].upper() == keyword:
                keyword = clean_list[0] # the first entry, preserving case
                arguments = clean_list[1:] # the rest is the argument
                break # break out of for loop at this point
        else: # terminal clause in for loop
            keyword, arguments = '', [] # the default position
    else: # line did not start with the keyword character
        keyword, arguments = '', [] # the default position
    return keyword, keyword.upper(), arguments

class SvxRecord:

    def __init__(self, p, encoding, line_number, context, line):
        '''Use this for storing results on a line per line basis'''
        self.path = p
        self.encoding = encoding.upper()
        self.line = line_number
        self.context = context
        self.text = line
        self.postscript = ''

# An iterator for iterating over files that can be called in context.
# Returns successive lines from the svx source tree, keeping track of
# begin and end statements.  A stack is used to keep track of the
# include files - items on the stack are tuples of file information.
# The initial stack entry acts as a sentinel to stop the iteration.

class SvxReader:
    
    def __init__(self, svx_file, open_hook=None, keyword_char='*', comment_char=';'):
        '''Instantiate with default properties'''
        self.keyword_char = keyword_char
        self.comment_char = comment_char
        self.open_hook = open_hook
        self.p = Path(svx_file).with_suffix('.svx') # add the suffix if not already present
        self.top_level = self.p
        self.context = [] # keep this as a list
        self.keywords = set(['INCLUDE', 'BEGIN', 'END'])
        self.stack = [(None, None, 0, '')] # initialise file stack with a sentinel
        self.fp, self.line_number, self.encoding, self.postscript = svx_open(self.p, hook=self.open_hook)
        if self.fp is None:
            raise FileNotFoundError(self.p)
        self.files_visited = 1

    def __iter__(self):
        '''Return an iterator for a top level svx file'''
        return self

    def __next__(self):
        '''Return the next line or stop iteration'''
        if not self.fp:
            raise StopIteration
        self.line, self.line_number = svx_readline(self.fp, self.line_number) # read line and increment the line number counter
        if not self.line:
            self.fp.close() # we ran out of lines for the file being currently processed
            self.p, self.fp, self.line_number, self.encoding = self.stack.pop() # back to the including file
            return next(self)
        self.line = self.line.strip() # remove leading and trailing whitespace then remove comments
        clean = self.line.split(self.comment_char)[0].strip() if self.comment_char in self.line else self.line
        keyword, uc_keyword, arguments = extract_keyword_arguments(clean, self.keywords, self.keyword_char) # preserving case
        if uc_keyword == 'BEGIN' and arguments: # add the survex context (assume lower case)
            self.context.append(arguments[0].lower())
        if uc_keyword == 'END' and arguments: # remove the most recent survex context
            self.context.pop()
        record = SvxRecord(self.p, self.encoding, self.line_number, self.context, self.line) # before push
        if uc_keyword == 'INCLUDE': # process an INCLUDE statement
            self.stack.append((self.p, self.fp, self.line_number, self.encoding)) # push onto stack
            filename = ' '.join(arguments).strip('"').replace('\\', '/') # remove any quotes and replace backslashes
            self.p = Path(self.p.parent, filename).with_suffix('.svx') # the new path (add the suffix if not already present)
            self.fp, self.line_number, self.encoding, record.postscript = svx_open(self.p, hook=self.open_hook, context=self.context)
            if self.fp is None:
                record.postscript = self.open_hook(self.p, self.context, 'not found')
                self.p, self.fp, self.line_number, self.encoding = self.stack.pop() # back to the including file
            else:
                self.files_visited = self.files_visited + 1
        return record

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        if type == FileNotFoundError:
            p, fp, line_number, encoding = self.stack.pop() # back to the including file
            print(f'{p}:{line_number}: {self.line.expandtabs()}')

if __name__ == "__main__":

# The following are used in colorized strings below and draws on
# https://stackoverflow.com/questions/5947742/how-to-change-the-output-color-of-echo-in-linux

    NC = '\033[0m'
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[0;33m'
    BLUE = '\033[0;34m'
    PURPLE = '\033[0;35m'
    CYAN = '\033[0;36m'

    import re
    import argparse

    keyword_char, comment_char = '*', ';' # for the time being

    parser = argparse.ArgumentParser(description='Analyze a survex data source tree.')
    parser.add_argument('svx_file', help='top level survex file (.svx)')
    parser.add_argument('-d', '--directories', action='store_true', help='absolute file paths instead of relative ones')
    parser.add_argument('-l', '--list-files', action='store_true', help='trace (output) the files that are visited')
    parser.add_argument('-k', '--keywords', default=None, help='a set of keywords (comma-separated, case insensitive) to use instead of default')
    parser.add_argument('-a', '--additional-keywords', default=None, help='a set of keywords (--ditto--) to add to the default')
    parser.add_argument('-e', '--excluded-keywords', default=None, help='a set of keywords (--ditto--) to exclude from the default')
    parser.add_argument('-t', '--totals', action='store_true', help='print totals for each keyword')
    parser.add_argument('-s', '--summarize', action='store_true', help='print a one-line summary')
    parser.add_argument('-g', '--grep', default=None, help='pattern to match (switch to grep mode)')
    parser.add_argument('-i', '--ignore-case', action='store_true', help='ignore case (when in grep mode)')
    parser.add_argument('-n', '--no-ignore-case', action='store_true', help='preserve case (when in keyword mode)')
    parser.add_argument('-x', '--context', action='store_true', help='include survex context in printed results')
    parser.add_argument('-y', '--omit-linen', action='store_true', help='omit line numbers in output')
    parser.add_argument('-c', '--color', action='store_true', help='colorize printed results')
    parser.add_argument('-q', '--quiet', action='store_true', help='only print errors (in case of -o only)')
    parser.add_argument('-o', '--output', help='(optional) output to spreadsheet (.ods, .xlsx)')
    args = parser.parse_args()

    open_hook = trace_hook if args.list_files else None

    if args.grep: # simple grep mode
        
        flags = re.IGNORECASE if args.ignore_case else 0
        pattern = re.compile(args.grep, flags=flags)
        no_matches = True
        with SvxReader(args.svx_file, open_hook=open_hook) as svx_reader:
            if svx_reader.postscript: # catch the trace of the initial file open
                print(svx_reader.postscript)
            for record in svx_reader:
                match = pattern.search(record.text)
                if match:
                    no_matches = False
                    match = match.group()
                    record_text = record.text.expandtabs()
                    record_path = str(record.path.absolute()) if args.directories else str(record.path)
                    record_context = '.'.join(record.context)
                    if args.color:
                        context = f'{BLUE}{record_context}{CYAN}' if args.context else ''
                        if args.omit_linen:
                            line = f'{PURPLE}{record_path}{CYAN}:{BLUE}{context}{CYAN}:{NC}{record_text}'
                        else:
                            line = f'{PURPLE}{record_path}{CYAN}:{GREEN}{record.line}{CYAN}:{BLUE}{context}{CYAN}:{NC}{record_text}'
                        line = line.replace(match, f'{RED}{match}{NC}')
                    else:
                        context = record_context if args.context else ''
                        if args.omit_linen:
                            line = f'{record_path}:{context}:{record_text}'
                        else:
                            line = f'{record_path}:{record.line}:{context}:{record_text}'
                    print(line)
                if record.postscript:
                    print(record.postscript)
        if no_matches:
            sys.exit(1) # reproduce what grep returns if there are no matches

    else: # keyword matching mode

        if args.keywords:
            keywords = set(args.keywords.upper().split(','))
        else:
            keywords = set(['INCLUDE', 'BEGIN', 'END'])

        if args.additional_keywords:
            to_be_added = set(args.additional_keywords.upper().split(','))
            keywords = keywords.union(to_be_added)

        if args.excluded_keywords:
            to_be_removed = set(args.excluded_keywords.upper().split(','))
            keywords = keywords.difference(to_be_removed)

        count = dict.fromkeys(keywords, 0)
        records = []

        with SvxReader(args.svx_file, open_hook=open_hook) as svx_reader:
            if svx_reader.postscript: # catch the trace of the initial file open
                print(svx_reader.postscript)
            for record in svx_reader:
                clean = record.text.split(comment_char)[0].strip() if comment_char in record.text else record.text
                keyword, uc_keyword, arguments = extract_keyword_arguments(clean, keywords, keyword_char) # preserving case
                if keyword:
                    record_text = record.text.expandtabs()
                    record_path = str(record.path.absolute()) if args.directories else str(record.path)
                    record_context = '.'.join(record.context)
                    if args.output:
                        arguments = ' '.join(arguments)
                        keyword = keyword if args.no_ignore_case else uc_keyword
                        records.append((record_path, record.encoding, record.line, record_context,
                                        keyword, arguments, record_text))
                    if args.totals or args.summarize or args.output:
                        count[uc_keyword] = count[uc_keyword] + 1
                    else:
                        if args.color:
                            context = f'{BLUE}{record_context}{CYAN}' if args.context else ''
                            if args.omit_linen:
                                line = f'{PURPLE}{record_path}{CYAN}:{BLUE}{context}{CYAN}:{NC}{record_text}'
                            else:
                                line = f'{PURPLE}{record_path}{CYAN}:{GREEN}{record.line}{CYAN}:{BLUE}{context}{CYAN}:{NC}{record_text}'
                            line = line.replace(keyword, f'{RED}{keyword}{NC}', 1)
                            line = line.replace(keyword_char, f'{RED}{keyword_char}{NC}', 1)
                            line = line.replace(f'{NC}{RED}', f'{RED}') # simplify
                        else:
                            context = record_context if args.context else ''
                            if args.omit_linen:
                                line = f'{record_path}:{context}:{record_text}'
                            else:
                                line = f'{record_path}:{record.line}:{context}:{record_text}'
                        print(line)
                if record.postscript:
                    print(record.postscript)

        top_level = str(svx_reader.top_level.absolute()) if args.directories else str(svx_reader.top_level)
        files_visited = f'{svx_reader.files_visited} files visited'

        if args.totals:
            for keyword in count:
                if args.color:
                    summary = f'{PURPLE}{top_level}{CYAN}:{RED}{keyword}{CYAN}:{NC} {count[keyword]} records found ({files_visited})'
                else:
                    summary = f'{top_level}:{keyword}: {count[keyword]} records found ({files_visited})'
                print(summary)

        if args.summarize or (args.output and not args.quiet):
            keyword_list = '|'.join(sorted(keywords))
            tot_count = sum(count.values())
            if args.color:
                summary = f'{PURPLE}{top_level}{CYAN}:{RED}{keyword_list}{CYAN}:{NC} {tot_count} records found ({files_visited})'
            else:
                summary = f'{top_level}:{keyword_list}: {tot_count} records found ({files_visited})'
            print(summary)

        if args.output:

            import pandas as pd
            schema = {'path':str, 'encoding':str, 'line':int, 'context':str,
                      'keyword':str, 'argument':str, 'full':str}
            df = pd.DataFrame(records, columns=schema.keys()).astype(schema)
            df.to_excel(args.output, index=False)
            if not args.quiet:
                print(f'Dataframe ({len(df.columns)} columns, {len(df)} rows) written to {args.output}')
