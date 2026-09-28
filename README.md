## Python code to analyze survex data source files

_Current version:_

v1.4 - tkinter GUI added courtesy of Claude Sonnet 5  
v1.3 - (current) small internal improvements  
v1.2 - reworked file trace mechanism  
v1.1 - reworked internals  
v1.0 - initial working version

### Latest

A rather nice GUI front end using tkinter was developed in half an
hour or so using Claude Sonnet 5.  To use this, download both
`svx_keywords.py` and `svx_keywords_gui.py` somewhere (both in the
same directory), and run the latter.  This brings up a GUI interface
with fields for selecting the `.svx` file, the keywords, and so on.
The GUI generates the required command line to run `svx_kaywords.py`
and the results are presented in a table.  Double-clicking on a table
entry should open the corresponding file at the relevant line.

### Summary

The python script `svx_keywords.py` in this repository analyzes survex
data source file trees (`.svx` files).  It can be used to search for
keywords such as file `INCLUDE` statements, `BEGIN` and `END` statements,
`ENTRANCE` tags, `FIX` points, co-ordinate system (`CS`)
declarations, and others as desired.  A 'grep-like' regular expression
pattern matching mode is also available.

The key feature that distinguishes this bespoke utility from generic
file system tools such as `find` and `grep` is that the code searches
through the _whole_ survex source file tree, following the file
inclusion statements, thus treating the survey data holistically
rather than as an _ad hoc_ collection of `.svx` files.  It reports results in
logical order, and additionally keeps track of the survex 'context' (station
naming hierarchy in terms of begin/end statements).

For example, to extract fixed points and co-ordinate system
definitions for the Dow-Prov system from the sample survex data source
file tree given in the `DowProv` directory, use
```
$ ./svx_keywords.py DowProv/DowProv -ck cs,fix
DowProv/DowProv.svx:41::*cs OSGB:SD
DowProv/DowProv.svx:42::*cs out EPSG:7405
DowProv/DowCave/DowCave.svx:16::*fix entrance 98378 74300 334
DowProv/ProvidencePot/ProvidencePot.svx:13::*fix entrance 99213 72887 401
DowProv/HagDyke.svx:14::*fix W 98981 73327 459
```
On a terminal screen, this output would be colorized (`-c` option).

### Installation

* Either clone or download the repository, or just download the 
key python script `svx_keywords.py`;

* put this script somewhere where it can be found,
for instance in the top level working directory for a survey project.

### Usage

#### As a command line tool

For keyword selection, `svx_keywords.py` provides a convenient
interface to searching for active keywords in the survex file tree.
Alternatively, one can search for a generic regular expression similar
to the unix `grep` command line tool.

The full usage is

```
usage: svx_keywords.py [-h] [-v] [-d] [-k KEYWORDS] [-a KEYWORDS]
            [-e KEYWORDS] [-t] [-s] [-g GREP]
	    [-i] [-n] [-x] [-c] [-q] [-o OUTPUT] svx_file

Analyze a survex data source tree.

positional arguments:
  svx_file                   top level survex file (.svx)

options:
  -h, --help                 show this help message and exit
  -d, --directories          absolute file paths instead of relative ones
  -l, --list-files           trace (output) the files that are visited
  -k, --keywords             a set of keywords to use instead of default
  -a, --additional-keywords  a set of keywords to add to the default
  -e, --excluded-keywords    a set of keywords to exclude from the default
  -t, --totals               print totals for each keyword
  -s, --summarize            print a one-line summary
  -g, --grep                 pattern to match (switch to grep mode)
  -i, --ignore-case          ignore case (when in grep mode)
  -n, --no-ignore-case       preserve case (when in keyword mode)
  -x, --context              include survex context in printed results
  -y, --omit-linen           omit line numbers in output
  -c, --color                colorize printed results
  -q, --quiet                only print errors (in case of -o only)
  -o, --output               (optional) output to spreadsheet (.ods, .xlsx)
```
The file extension (`.svx`) is supplied automatically if missing, as
in the initial example.

The default action is to search and report all results for keywords
from the following set: `INCLUDE`, `BEGIN`, `END`.

The keyword set can be modified by using the `-k`, `-a` and `-e`
options as follows.  The `-k` option is used to specify an alternative
set of keywords to search for.  The argument should be a
comma-separated list of keywords (case insensitive) with no
additional spaces, for example `-k cs,fix` used in the introductory
example.  The `-a` and `-e` options work similarly, but _modify_ the
default keyword set rather than replacing it.

Note that only _active_ keywords are found, not any that have been
commented out (see 'grep' mode for this).

With the `-o` option, the results are saved to a spreadsheet.  The top
row is a header row, then there is one row for each keyword instance,
in the order in which they appeared when parsing the sources.  The
columns are

* the file path for the detected keyword;
* the detected character encoding of the file (`UTF-8`, `ISO-8859-1`);
* the line number in the file;
* the current survex context from begin statements;
* the keyword itself, capitalized unless the `-n` option is chosen;
* the argument(s) following the keyword, if any;
* the full original line in the survex file.

For example, to save a spreadsheet for the Dow-Prov case, use
```bash
./svx_keywords.py DowProv/DowProv -o dp.ods
```
The resulting spreadsheet, here in open document format (`.ods`), can be
loaded into Excel or libreoffice.

If `-o` is not specified the command writes the extracted information
as a list of file names and line numbers, with the associated lines,
to terminal output.  With the `-x` option, additional survex context
information is included.  Summary information can be obtained with the
`-t` and `-s` options.  These can be combined with each other (and
also with `-o`, which always prints a summary unless `-q` is
specified).  If the `-c` option is present for any of these, the
terminal output is colorized like `grep`, with the path information
(if present) and keywords additionally highlighted.

The special 'grep' mode is accessed by specifying `-g`, with a regular
expression, or just a simple string.  In this case, the set of
keywords is ignored, as are the `-s`, `-t` and `-o` options, and all
lines which contain a match are reported to the terminal window, with
the match highlighted. Setting `-i` ignores case in the pattern
matching.  The output is very similar to the standard `grep` alluded
to above, with the exception that line numbers are always included,
and context can be additionally included with the `-x` option.  Also,
if there are no pattern matches in 'grep' mode, the script returns
with exit code 1 but no lines of output (modeled on the behavior of
`grep` itself).

The 'grep' mode can be used to search for _all_ instances of a
keyword in the files, not just active ones that are reported by the
default mode of the tool.  This can be useful to find instances where
keywords have been 'commented out'.

The `-l` option traces the files that are visited, reporting results
in a format similar to the keyword or grep results (so, the `-d`, `-x`
and `-c` options are also in play).  This can be handy to track which
files are actually part of the survex data tree.  A pure list can be
generated by invoking the script with a non-existent keyword, for
example:
```
$ ./svx_keywords.py DowProv/DowProv -clk xyzzy
DowProv/DowProv.svx:0::<entered>
DowProv/DowCave/DowCave.svx:0::<entered>
DowProv/DowCave/dow1.svx:0::<entered>
... (49 files in total)
```

#### In a python script or jupyter notebook

The script `svx_keywords.py` can also be loaded as a python module in
a python script or jupyter notebook from which an iterator can be
created as a context manager to iterate over all the lines in the
files in the survex data tree, in order.  The basic usage is
```python
from svx_keywords import SvxReader

with SvxReader('DowProv/DowProv') as svx_reader:
    for record in svx_reader:
    	# do something with the record ...
```
The returned 'record' has fields for:

* `.path` = the file path as a `Path` object;
* `.encoding` = the detected file encoding;
* `.line` = line number (integer) in the file;
* `.context` = survex context inferred from begin statements, as a list;
* `.text` = the line itself

For example, to print all entries which begin with `*fix` do

```python
from svx_keywords import SvxReader

with SvxReader('DowProv/DowProv') as svx_reader:
    for record in svx_reader:
        if record.text.startswith('*fix'):
            print(record.text)
```
More details of the constructor and function calls can be found
inside the script itself.

#### Longer example: extracting fixed points

```python
import pandas as pd
from svx_keywords import SvxReader
svx_file, output_csv = 'DowProv/DowProv.svx', 'DowProv_fixes.csv' # <-- change these
records = [] # will grow as records are added
with SvxReader('DowProv/DowProv') as svx_reader:
    for record in svx_reader:
        if record.text.startswith('*cs') and not record.text.startswith('*cs out'):
            crs = record.text.removeprefix('*cs').strip() # record the CRS
        if record.text.startswith('*fix'):
            parts = record.text.removeprefix('*fix').strip().replace(';', ' ').split()
            station = '.'.join(record.context + [parts[0]]) # context + station name
            x, y, z = [int(x) for x in parts[1:4]]
            records.append((x, y, z, station,  crs, f'{record.path}:{record.line}'))
schema = {'x':int, 'y':int, 'z':int, 'station':str, 'crs':str, 'location':str}
df = pd.DataFrame(records, columns=schema.keys()).astype(schema)
csv = df.to_csv(index=False, header=False)
with open(output_csv, 'w') as f:
    f.write(csv)
```
Here we extract the fixed points in a survex file tree, keeping track
of the co-ordinate reference system (CRS) in force.  We dismantle the
argument of the `*fix` keyword to extract the station name and x, y
and z co-ordinates, taking care to allow for the possibility of
comments by replacing a comment character by a space, then
splitting on spaces.  The data is accumulated in a list of records
(tuples) which is converted to a pandas dataframe then written to a
file as comma-separated values (csv).  The result here is:
```
98378,74300,334,dowcave.dow1.1,OSGB:SD,DowProv/DowCave/DowCave.svx:15
99213,72887,401,providencepot.ppot1.1,OSGB:SD,DowProv/ProvidencePot/ProvidencePot.svx:12
98981,73327,459,hagdyke.W,OSGB:SD,DowProv/HagDyke.svx:14
```
This contains the x, y, z co-ordinates and the full station name,
followed by the CRS, and finally the file in which the `*fix` appears
and the line number within that file.

As it stands this piece of code assumes there are no spaces after the
keyword character `*`, and also that the keyword is lower case.  With 
a bit more care this could be fixed up, and in any
case one can check for such cases by running:
```
$ ./svx_keywords.py -ck cs,fix DowProv/DowProv
```

### Technical notes

Some complications arise because survex is quite liberal about what
input it can take.

One of these concerns the character encoding for the data files.  In
some cases these can contain characters which are not recognised as
UTF-8 but are in the extended ASCII character set, such as
the degree &deg; symbol in ISO-8859-1.  To handle this the module
attempts to determine the character encoding for each file it is asked
to read from, before parsing the file.  This is done rather crudely by
slurping the entire contents of the file and looking for decoding
exceptions.  Currently the only encodings tested for are 'UTF-8' and
'ISO-8859-1' (aka Latin 1).

Another issue concerns the use of capitalisation for keywords, file
names, and the survex path itself.  The parsing algorithm is designed
to work around these issues BUT it is assumed that it is acceptable
for survey path names introduced by begin and end statements to be
forced to lower case.  For keywords, capitalisation is irrelevant, for
example `*BEGIN` and `*Begin` are equally valid as `*begin`.  Also,
there can be space between the keyword character and the keyword
itself so that `* begin` is the same as `*begin`.  Again the code
should handle these cases transparently. 

Generally if a survex file can be successfully processed by `cavern`,
then it ought to be parsable by the present script.  It has
been checked against the Leck-Masongill data set and the
EaseGill-Pippikin data set, as well as the Dow-Prov case.

### Open issues

* Intercept `set` commands, to set comment and keyword characters.
* Intercept `case preserve|toupper|tolower` and interpret accordingly.

If there are issues parsing survex files with these scripts, please
let me know!  
Also, feel free to request/suggest additional features.

### Copying

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

### Copyright

This program is copyright &copy; 2023 Patrick B Warren.  
