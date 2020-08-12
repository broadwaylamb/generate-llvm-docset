#!/usr/bin/env python3

import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import xml.etree.ElementTree as ElementTree
from argparse import ArgumentParser
from pathlib import Path


# Simplified version of https://github.com/verigak/progress
class ProgressBar(object):
    """Class for showing a nice progress bar in the console when running docsetutil"""

    HIDE_CURSOR = '\x1b[?25l'
    SHOW_CURSOR = '\x1b[?25h'

    def __init__(self, file=sys.stderr):
        self.index = 0
        self.file = file
        self.max = None

        print(self.HIDE_CURSOR, end='', file=self.file)
        self.update()

    def update(self):
        width = 32
        phases = (' ', '▏', '▎', '▍', '▌', '▋', '▊', '▉', '█')
        num_phases = len(phases)
        filled_len = width * self.progress
        num_fill = int(filled_len)                         # Number of full chars
        phase = int((filled_len - num_fill) * num_phases)  # Phase of last char
        num_empty = width - num_fill                       # Number of empty chars

        bar = phases[-1] * num_fill
        current = phases[phase] if phase > 0 else ''
        empty = ' ' * max(0, num_empty - len(current))

        self.writeln('Progress: |{}{}{}| {:.2f}%'.format(bar, current, empty, self.percent))

    def start(self, max_value):
        self.max = float(max_value)
        self.update()

    def writeln(self, line):
        print('\r\x1b[K', end='', file=self.file)  # Clear line
        print(line, end='', file=self.file)
        self.file.flush()

    def finish(self):
        print(file=self.file)
        print(self.SHOW_CURSOR, end='', file=self.file)

    def next(self):
        self.index += 1
        self.update()

    @property
    def started(self):
        return self.max is not None

    @property
    def percent(self):
        return self.progress * 100.0

    @property
    def progress(self):
        if self.max is not None:
            return min(1.0, self.index / self.max)
        else:
            return 0.0


class ToolNotFoundError(Exception):
    """Raised when we cannot detect doxygen or dot in the system"""
    pass


class DocSetGenerator:
    """This class is responsible for the whole thing"""

    def __init__(self,
                 llvm_version,
                 clean,
                 doxygen_path,
                 dot_path,
                 docsetutil_path,
                 icon_path,
                 skip_docset_generation,
                 quiet,
                 verbose,
                 logger):

        self.llvm_version = llvm_version
        self.clean = clean

        if doxygen_path:
            self.doxygen_path = str(doxygen_path)
        else:
            self.doxygen_path = shutil.which('doxygen')

        if not self.doxygen_path or not Path(self.doxygen_path).exists():
            raise ToolNotFoundError('Could not find doxygen. Provide a path to doxygen tool via the --doxygen-path '
                                    'command line option or install doxygen via \'brew install doxygen\'')

        if dot_path:
            self.dot_path = str(dot_path)
        else:
            self.dot_path = shutil.which('dot')

        if not self.dot_path or not Path(self.dot_path).exists():
            raise ToolNotFoundError('Could not find dot. Provide a path to dot tool via the --dot-path '
                                    'command line option or install dot via \'brew install graphviz\'')

        self.docsetutil_path = docsetutil_path

        self.icon_path = icon_path

        self.skip_docset_generation = skip_docset_generation

        self.quiet = quiet
        self.verbose = verbose
        self.logger = logger

    def log(self, msg, color):
        if self.quiet:
            return
        self.logger(msg, color)

    def download_llvm_tarball(self):
        """
        Downloads the LLVM source of the specified version from http://releases.llvm.org,
        or uses the existing tarball.

        :returns: The path of the downloaded tarball
        :rtype: Path
        """

        tarball = Path('llvm-{}.src.tar.xz'.format(self.llvm_version))

        if tarball.exists():
            if self.clean:
                self.log('Deleting {}...'.format(tarball), 'cyan')
                tarball.unlink()
            else:
                self.log('Using existing tarball {}...'.format(tarball), 'cyan')
                return tarball

        tarball_url = 'https://github.com/llvm/llvm-project/releases/download/llvmorg-{}/{}'.format(self.llvm_version, tarball)

        self.log('Downloading {} from {}...'.format(tarball, tarball_url), 'magenta')

        urllib.request.urlretrieve(tarball_url, tarball)

        return tarball

    def extract_llvm_tarball(self, tarball_path):
        """
        Extracts the downloaded tarball into the directory near the tarball.

        :param tarball_path: The name of the downloaded tarball
        :type tarball_path: Path
        :return: The path of the directory where the files have been extracted
        :rtype: Path
        """

        src_dir = Path('llvm-{}.src'.format(self.llvm_version))

        if src_dir.exists():
            if self.clean:
                self.log('Deleting {}...'.format(src_dir), 'cyan')
                shutil.rmtree(src_dir)
            else:
                self.log('Using existing LLVM source in {}...'.format(src_dir), 'cyan')
                return src_dir

        self.log('Extracting {} into {}...'.format(tarball_path, src_dir), 'magenta')

        try:
            archive = tarfile.open(tarball_path, 'r')
            archive.extractall()
        except KeyboardInterrupt:
            self.log('Cleaning up...', 'cyan')
            shutil.rmtree(src_dir, ignore_errors=True)
            sys.exit(1)

        return src_dir

    def configure_doxygen(self, llvm_dir):
        """
        Creates the doxygen.cfg file for generating documentation

        :param llvm_dir: The source directory of LLVM
        :type  llvm_dir: Path
        :return: The path of the generated doxygen.cfg file
        :rtype: Path
        """

        docs_dir = llvm_dir / 'docs'
        doxygen_cfg_in = docs_dir / 'doxygen.cfg.in'

        self.log('Configuring doxygen using {}...'.format(doxygen_cfg_in), 'magenta')

        with doxygen_cfg_in.open() as config_template_f:
            config_template = config_template_f.read()

        replacements = {
            'PACKAGE_VERSION': self.llvm_version,
            'abs_top_builddir': '.',
            'abs_top_srcdir': str(docs_dir),
            'enable_searchengine': 'YES' if self.skip_docset_generation else 'NO',
            'searchengine_url': '',
            'enable_server_based_search': 'NO',
            'enable_external_search': 'NO',
            'extra_search_mappings': '',
            'llvm_doxygen_generate_qhp': 'NO',
            'llvm_doxygen_qch_filename': '',
            'llvm_doxygen_qhp_namespace': '',
            'llvm_doxygen_qhelpgenerator_path': '',
            'llvm_doxygen_qhp_cust_filter_name': '',
            'llvm_doxygen_qhp_cust_filter_attrs': '',
            'DOT_IMAGE_FORMAT': 'svg',
            'DOT': self.dot_path
        }

        config = re.sub(r'@(\w+)@', lambda match: replacements[match.group(1)], config_template)
        config += 'DOT_TRANSPARENT = YES\nQUIET = {}\n'.format('NO' if self.verbose else 'YES')

        if not self.skip_docset_generation:
            config += 'GENERATE_DOCSET = YES\n'
            config += 'DOCSET_BUNDLE_ID = org.doxygen.LLVM\n'
            config += 'DOCSET_PUBLISHER_ID = org.doxygen.LLVM\n'
            config += 'DOCSET_PUBLISHER_NAME = LLVM\n'
            config += 'DISABLE_INDEX = YES\n'

        doxygen_cfg = Path('doxygen.cfg')

        with doxygen_cfg.open('w') as config_f:
            config_f.write(config)

        return doxygen_cfg

    def run_doxygen(self, doxygen_cfg):
        """
        Generates HTML documentation using doxygen

        :param doxygen_cfg: The path of the doxygen.cfg file
        :type  doxygen_cfg: Path
        :returns The path of the directory with generated HTML documentation
        :rtype: Path
        """

        html_doc = doxygen_cfg.parent / 'doxygen' / 'html'

        if html_doc.exists():
            if self.clean:
                self.log('Deleting {}...'.format(html_doc), 'cyan')
                shutil.rmtree(html_doc)
            else:
                self.log('Using existing HTML documentation in {}...'.format(html_doc), 'cyan')
                return html_doc

        command = [self.doxygen_path, str(doxygen_cfg)]

        self.log('Generating HTML documentation (this may take some time)...', 'magenta')
        self.log('Running {}'.format(' '.join(command)), 'blue')

        try:
            subprocess.check_call(command,
                                  stdout=(sys.stdout if self.verbose else subprocess.DEVNULL),
                                  stderr=(sys.stderr if self.verbose else subprocess.DEVNULL))
        except KeyboardInterrupt:
            self.log('Cleaning up...', 'cyan')
            shutil.rmtree(html_doc, ignore_errors=True)
            sys.exit(1)

        return html_doc

    def __run_docsetutil(self, docset):
        """
        Runs docsetutil, which creates an SQLite index of HTML documentation files

        :param docset: The docset to index
        :type  docset: Path
        """
        command = [str(self.docsetutil_path), 'index', str(docset)]

        self.log('Running {}'.format(' '.join(command)), 'blue')

        class ProgressTracker:

            def __init__(self):
                self.progress_bar = ProgressBar()

            def __call__(self, current_line):
                try:
                    if not self.progress_bar.started:
                        match = re.search(r'\((\d+) nodes\)', current_line)
                        if match:
                            self.progress_bar.start(int(match.group(1)))
                        else:
                            return
                    else:
                        self.progress_bar.next()

                except ValueError:
                    return

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.progress_bar.finish()

        # From https://gist.github.com/dhrrgn/6073120 with modifications:

        try:
            if self.verbose:
                subprocess.check_call(command, stdout=sys.stdout, stderr=sys.stderr)
            else:
                process = subprocess.Popen(command, stdout=subprocess.PIPE)

                with ProgressTracker() as progress_tracker:
                    while process.poll() is None:
                        line = process.stdout.readline(100).decode('utf-8')
                        if line and line != "":
                            progress_tracker(line)

                    # Sometimes the process exits before we have all of the output, so
                    # we need to gather the remainder of the output.
                    remainder = process.communicate()[0]
                    if remainder:
                        progress_tracker(remainder)

                if process.returncode != 0:
                    raise subprocess.CalledProcessError(returncode=process.returncode, cmd=command)
        except KeyboardInterrupt:
            self.log('Cleaning up...', 'cyan')
            try:
                for dbIndex in docset.glob('Contents/Resources/docSet*'):
                    dbIndex.unlink()
            except OSError:
                pass
            sys.exit(1)

    def generate_docset_from_html(self, html_doc):
        """
        Creates the org.doxygen.LLVM.docset file and performs indexing with docsetutil

        :param html_doc: The directory with the generated HTML documentation
        :type  html_doc: Path
        :return: The path of the generated .docset file
        :rtype: Path
        """

        docset = Path('LLVM.docset')

        docset_contents = docset / 'Contents'
        docset_resources = docset_contents / 'Resources'
        docset_documents = docset_resources / 'Documents'
        nodes_xml = html_doc / 'Nodes.xml'
        tokens_xml = html_doc / 'Tokens.xml'
        info_plist = html_doc / 'Info.plist'

        if docset.exists():
            if self.clean:
                self.log('Deleting {}...'.format(docset), 'cyan')
            else:
                self.log('Using existing docset in {}...'.format(docset), 'cyan')
                return docset

        self.log('Creating {} (this may take some time)...'.format(docset), 'magenta')

        try:
            docset_resources.mkdir(parents=True, exist_ok=True)

            # noinspection PyTypeChecker
            nodes_xml = Path(shutil.copy(nodes_xml, docset_resources))

            # noinspection PyTypeChecker
            tokens_xml = Path(shutil.copy(tokens_xml, docset_resources))

            # noinspection PyTypeChecker
            shutil.copy(info_plist, docset_contents)

            # noinspection PyTypeChecker
            shutil.copytree(html_doc,
                            docset_documents,
                            ignore=shutil.ignore_patterns('Nodes.xml',
                                                          'Tokens.xml',
                                                          'Info.plist',
                                                          str(docset)))
        except KeyboardInterrupt:
            self.log('Cleaning up...', 'cyan')
            shutil.rmtree(docset, ignore_errors=True)
            sys.exit(1)

        self.__run_docsetutil(docset)

        nodes_xml.unlink()
        tokens_xml.unlink()

        return docset

    def add_icon(self, docset):
        """
        Copies the icon.png file to the .docset file

        :param docset: The path of the generated .docset file
        :type  docset: Path
        """
        self.log('Adding the nice dragon icon...', 'magenta')

        # noinspection PyTypeChecker
        shutil.copy(self.icon_path, docset)

    def patch_info_plist(self, docset):
        """
        Modifies the Info.plist file of the docset for Dash, namely adds support
        for online redirection.

        :param docset: The path of the generated .docset file
        :type  docset: Path
        """
        self.log('Patching Info.plist file...', 'magenta')

        info_plist = docset / 'Contents' / 'Info.plist'

        tree = ElementTree.parse(info_plist)

        plist_dict = tree.getroot().find('dict')

        doc_set_platform_family_key = None
        doc_set_platform_family_value = None

        for tag in plist_dict:
            if tag.tag == 'key' and tag.text == 'DocSetPlatformFamily':
                doc_set_platform_family_key = tag
                continue
            if doc_set_platform_family_key is not None:
                doc_set_platform_family_value = tag
                break

        if doc_set_platform_family_value is not None:
            doc_set_platform_family_value.text = 'llvm'

        # Preserve indentation in the existing plist file:
        # Take the tail of the first child and add the same tail to the last child
        _, first_value, *_, last_value = plist_dict.iter()
        last_value.tail = first_value.tail

        # Support online redirection
        # https://kapeli.com/docsets#onlineRedirection
        online_redirection_key = ElementTree.Element('key')
        online_redirection_key.text = 'DashDocSetFallbackURL'
        online_redirection_key.tail = last_value.tail
        online_redirection_value = ElementTree.Element('string')
        online_redirection_value.text = 'http://llvm.org/doxygen/'
        online_redirection_value.tail = '\n'
        plist_dict.append(online_redirection_key)
        plist_dict.append(online_redirection_value)

        tree.write(info_plist)

    def run(self):
        """
        The main method of this class.

        Downloads LLVM tarball, extracts it, runs doxygen and generates the docset for Dash.
        """

        tarball = self.download_llvm_tarball()

        llvm_dir = self.extract_llvm_tarball(tarball)

        doxygen_cfg = self.configure_doxygen(llvm_dir)

        html_docs = self.run_doxygen(doxygen_cfg)

        if not self.skip_docset_generation:
            docset = self.generate_docset_from_html(html_docs)

            self.add_icon(docset)

            self.patch_info_plist(docset)

        self.log('Done!', 'green')


def colorized_stderr_log(string, color):
    """
    Colorized terminal output to stderr

    :param string: The string to print
    :type  string: str
    :param color: The color of the output
    :type  color: str
    """

    colors = {
        'black': '\u001b[30m',
        'red': '\u001b[31m',
        'green': '\u001b[32m',
        'yellow': '\u001b[33m',
        'blue': '\u001b[34m',
        'magenta': '\u001b[35m',
        'cyan': '\u001b[36m',
        'white': '\u001b[37m'
    }

    colors['warning'] = colors['yellow']
    colors['error'] = colors['red']

    sequence = colors[color.lower()]

    if sequence:
        print(sequence + string + '\u001b[0m', file=sys.stderr)
    else:
        print(string, file=sys.stderr)


if __name__ == '__main__':

    parser = ArgumentParser()

    parser.add_argument('llvm_version',
                        help='LLVM version string (e. g. 8.0.0)')

    parser.add_argument('--clean',
                        help='Download and regenerate everything from scratch',
                        action='store_true')

    parser.add_argument('--doxygen-path',
                        dest='doxygen_path',
                        help='The path to doxygen executable')

    parser.add_argument('--dot-path',
                        dest='dot_path',
                        help='The path to dot (from Graphviz) executable')

    parser.add_argument('--skip-docset-generation',
                        dest='skip_docset_generation',
                        help='Only generate HTML documentation, without Dash .docset file',
                        action='store_true')

    parser.add_argument('-q',
                        '--quiet',
                        help='Suppress the output',
                        action='store_true')

    parser.add_argument('-v',
                        '--verbose',
                        help='Show output of doxygen and other tools',
                        action='store_true')

    args = parser.parse_args()

    docsetutil = Path(__file__).parent / 'DocSetUtil' / 'Developer' / 'usr' / 'bin' / 'docsetutil'
    icon = Path(__file__).parent / 'icon.png'

    try:

        generator = DocSetGenerator(args.llvm_version,
                                    args.clean,
                                    args.doxygen_path,
                                    args.dot_path,
                                    docsetutil,
                                    icon,
                                    args.skip_docset_generation,
                                    args.quiet,
                                    args.verbose,
                                    colorized_stderr_log)

        generator.run()
    except ToolNotFoundError as e:
        colorized_stderr_log(str(e), 'error')
        parser.exit(status=1)
    except subprocess.CalledProcessError as e:
        colorized_stderr_log('{} failed with exit code {}'.format(' '.join(e.cmd), e.returncode), 'error')
        if not args.verbose:
            colorized_stderr_log('Try rerunning with --verbose flag to see what went wrong', 'error')
        parser.exit(status=1)
