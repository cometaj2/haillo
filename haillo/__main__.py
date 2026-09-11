import sys
import re
import shutil
import textwrap

from . import package
from . import config
from . import hutils
from . import haillo


# prototype generator to identity generators as a type
def generator():
    yield

def main():
    if len(sys.argv) == 1:
        haillo.main()

    if len(sys.argv) == 2:
        if sys.argv[1] == "--version":
            show_dependencies()

        elif sys.argv[1] == "help":
            helper = display_man_page(config.manpage_path)

            def generator():
                yield ('stdout', helper)

            output = generator()

            no_newline = False
            if isinstance(output, type(generator())):
                dest = None
                stdout_bytes_written = 0
                stderr_bytes_written = 0
                for dest, chunk in output:  # Now unpacking tuple of (dest, chunk)
                    stream = sys.stderr if dest == 'stderr' else sys.stdout
                    f = getattr(stream, 'buffer', stream)
                    if chunk:
                        f.write(chunk)
                        f.flush()

                        # Track total bytes written to each stream
                        if dest == 'stdout':
                            stdout_bytes_written += len(chunk)
                        else:
                            stderr_bytes_written += len(chunk)

                        if dest == 'stderr':
                            try:
                                error = chunk.decode('utf-8')
                                eprint(error)
                            except UnicodeDecodeError:
                                eprint(chunk)

                            # Add newline for stderr before exit if needed
                            if stderr_bytes_written > 0 and not no_newline:
                                sys.stderr.write('\n')
                            sys.exit(1)

                # Add newlines after all output so that other *nix tools will work correctly
                if not no_newline:
                    if dest == 'stdout' and stdout_bytes_written > 0:
                        sys.stdout.write('\n')
                    elif dest == 'stderr' and sterr_bytes_written > 0:
                        eprint('\n')
            else:
                error = "hcli_core: unexpected non-generator type."
                eprint(error)
                if not no_newline:
                    eprint('\n')

            sys.exit(0)

        else:
            help()

    else:
        help()

def show_dependencies():
    def parse_dependency(dep_string):
        # Common version specifiers
        specifiers = ['==', '>=', '<=', '~=', '>', '<', '!=']

        # Find the first matching specifier
        for specifier in specifiers:
            if specifier in dep_string:
                name, version = dep_string.split(specifier, 1)
                return name.strip(), specifier, version.strip()

        # If no specifier found, return just the name
        return dep_string.strip(), '', ''

    dependencies = ""
    for dep in package.dependencies:
        name, specifier, version = parse_dependency(dep)
        if version:  # Only add separator if there's a version
            dependencies += f" {name}/{version}"
        else:
            dependencies += f" {name}"

    print(f"haillo/{package.__version__}{dependencies}")

def help():
    hutils.eprint("for help, use:\n")
    hutils.eprint("  haillo help")
    sys.exit(2)

# displays a man page (file) located on a given path
def display_man_page(path):
    with open(path, "r") as f:
        text = f.read()
        return troff_to_text(text).encode('utf-8')
    f.close()

def troff_to_text(content, width=None):
    # If width is not specified, try to get the terminal size
    if width is None:
        try:
            columns, _ = shutil.get_terminal_size()
            width = columns
        except Exception:
            # Fall back to 80 if we can't determine terminal size
            width = 80

    # Helper function to handle troff escape characters
    def process_escapes(text):
        # Generic rule: remove backslash before any character
        text = re.sub(r'\\(.)', r'\1', text)
        return text

    # Extract the man page title from .TH line
    title_match = re.search(r'\.TH\s+(\S+)\s+(\S+)', content)
    if title_match:
        name = title_match.group(1)
        section = title_match.group(2)
        name_section = f"{name}({section})"
        centered_text = "User Commands"

        # Calculate proper alignment positions for header
        left_text = name_section
        center_text = centered_text
        right_text = name_section

        # Create properly aligned header
        left_part = left_text
        center_start = (width - len(center_text)) // 2
        center_part = " " * (center_start - len(left_part)) + center_text
        right_start = width - len(right_text)
        right_part = " " * (right_start - len(left_part) - len(center_part)) + right_text

        header = left_part + center_part + right_part

        # Create right-aligned footer
        footer = " " * (width - len(name_section)) + name_section
    else:
        header = ""
        footer = ""

    # Initialize result with header
    result = [header, ""] if header else []

    # Process the content line by line
    lines = content.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line.startswith('.B'):
            # For top-level .B directives, collect them as part of the next regular text
            bold_text = line[2:].strip()
            i += 1
            continue

        # Process .SH (section header)
        if line.startswith('.SH'):
            # Add only a single blank line before section header
            if result and result[-1] != "":
                result.append("")
            section_name = process_escapes(line[4:].strip().strip('"'))
            result.append(section_name)
            i += 1

            # Process the content until the next .SH or end
            section_content = []
            paragraph_lines = []
            is_first_ip = True  # Flag to track first .IP in section

            while i < len(lines):
                current = lines[i].strip()

                # Check for next section header
                if current.startswith('.SH'):
                    break

                if current.startswith('.B'):
                    bold_text = current[2:].strip()
                    if bold_text:
                        paragraph_lines.append(bold_text)
                    i += 1
                    continue

                # Process subsection header (.SS)
                if current.startswith('.SS'):
                    if paragraph_lines:
                        para_text = ' '.join(paragraph_lines)
                        wrapped_lines = textwrap.wrap(para_text, width=width-7)
                        for wrapped_line in wrapped_lines:
                            result.append(f"       {wrapped_line}")
                        result.append("")
                        paragraph_lines = []

                    if result and result[-1] != "":
                        result.append("")
                    subsection_name = process_escapes(current[4:].strip().strip('"'))
                    result.append(f"   {subsection_name}")
                    i += 1
                    is_first_ip = True  # Reset flag for new subsection
                    continue

                # Process indented paragraph (.IP)
                if current.startswith('.IP'):
                    if paragraph_lines:
                        para_text = ' '.join(paragraph_lines)
                        wrapped_lines = textwrap.wrap(para_text, width=width-7)
                        for wrapped_line in wrapped_lines:
                            result.append(f"       {wrapped_line}")
                        paragraph_lines = []

                    # Add blank line before .IP entry only if it's not the first .IP
                    if not is_first_ip:
                        result.append("")

                    is_first_ip = False  # Update flag after processing first .IP

                    item_match = re.search(r'\.IP\s+"([^"]+)"', current)
                    if item_match:
                        item_name = process_escapes(item_match.group(1))
                    else:
                        item_name = process_escapes(current[3:].strip().strip('"'))

                    result.append(f"       {item_name}")
                    i += 1

                    desc_text = []
                    # Check for .B immediately following .IP
                    if i < len(lines) and lines[i].strip().startswith('.B'):
                        bold_text = process_escapes(lines[i].strip()[2:].strip())
                        if bold_text:
                            desc_text.append(bold_text)
                        i += 1

                    while i < len(lines) and not (lines[i].strip().startswith('.') and 
                                               not lines[i].strip().startswith('.br') and 
                                               not lines[i].strip().startswith('.sp') and
                                               not lines[i].strip().startswith('.B')):
                        if lines[i].strip().startswith('.sp'):
                            if desc_text:
                                wrapped_desc = textwrap.wrap(' '.join(desc_text), width=width-14)
                                for wrapped_line in wrapped_desc:
                                    result.append(f"              {wrapped_line}")
                                result.append("")
                                desc_text = []
                        elif lines[i].strip().startswith('.br'):
                            if desc_text:
                                wrapped_desc = textwrap.wrap(' '.join(desc_text), width=width-14)
                                for wrapped_line in wrapped_desc:
                                    result.append(f"              {wrapped_line}")
                                desc_text = []
                        elif lines[i].strip().startswith('.B'):
                            if desc_text:
                                wrapped_desc = textwrap.wrap(' '.join(desc_text), width=width-14)
                                for wrapped_line in wrapped_desc:
                                    result.append(f"              {wrapped_line}")
                                desc_text = []
                        else:
                            if not lines[i].strip().startswith('.'):
                                desc_text.append(lines[i].strip())
                        i += 1

                    if desc_text:
                        wrapped_desc = textwrap.wrap(' '.join(desc_text), width=width-14)
                        for wrapped_line in wrapped_desc:
                            result.append(f"              {wrapped_line}")

                    continue

                if current.startswith('.sp'):
                    if paragraph_lines:
                        para_text = ' '.join(paragraph_lines)
                        wrapped_lines = textwrap.wrap(para_text, width=width-7)
                        for wrapped_line in wrapped_lines:
                            result.append(f"       {wrapped_line}")
                        result.append("")
                        paragraph_lines = []
                    i += 1
                    continue

                if current.startswith('.br'):
                    if paragraph_lines:
                        para_text = ' '.join(paragraph_lines)
                        wrapped_lines = textwrap.wrap(para_text, width=width-7)
                        for wrapped_line in wrapped_lines:
                            result.append(f"       {wrapped_line}")
                        paragraph_lines = []
                    i += 1
                    continue

                if not current.startswith('.'):
                    processed_text = process_escapes(current)
                    paragraph_lines.append(processed_text)

                i += 1

            if paragraph_lines:
                para_text = ' '.join(paragraph_lines)
                wrapped_lines = textwrap.wrap(para_text, width=width-7)
                for wrapped_line in wrapped_lines:
                    result.append(f"       {wrapped_line}")

            continue

        i += 1

    # Add footer with empty line before it
    if footer:
        result.append("")
        result.append(footer)

    return '\n'.join(result)
