import os
import random
import re
import tqdm
from pygments.lexers import get_lexer_for_filename, ClassNotFound
from pygments.token import Token
import json

DIR = "intellij-community"


def get_files(directory: str) -> list:
    """
    Returns a list of all files in a directory.
    """
    res = []
    for root, dirs, files in os.walk(directory):
        for filename in files:
            res.append(os.path.join(root, filename))
    return res


def get_extension(file_name: str) -> str:
    """
    Returns a file extension.
    """
    return os.path.splitext(file_name)[-1]


def get_file_extensions(directory: str) -> list:
    """
    Returns a list of pairs (extension, (number of files with that extension, example file)).
    Pairs are sorted in descending order by the number of files.
    """
    counter = dict()
    for file in get_files(directory):
        ext = get_extension(file)
        if ext not in counter:
            counter[ext] = [0, file]
        counter[ext][0] += 1
    return list(sorted(counter.items(), key=lambda x: -x[1][0]))


def get_files_by_extension(directory: str, ext: str) -> list:
    """
    Returns a list of all files in the directory with the given extension.
    """
    return list((file for _, _, files in os.walk(directory) for file in files if get_extension(file) == ext))


def get_balance(line: str, braces: str) -> int:
    """
    Get the brace balance of the given line (number of open braces - number of closing braces).
    Pair of braces is store in braces parameter.
    """
    return sum(map(lambda x: 1 if x == braces[0] else -1 if x == braces[1] else 0, line))


def extract_curly_oneliner(start: int, header: str, line: str) -> tuple[int, str, str]:
    """
    Extracts one-liner of the form
    <fun name(...) ... {...}>
    """
    start_clean, end_clean = -1, -1
    for i, c in enumerate(line):
        if c == '{' and start_clean == -1:
            start_clean = i + 1
        if c == '}':
            end_clean = i
    clean_body = line[start_clean:end_clean]
    return start, header, clean_body


def extract_curly_function(start: int, initial_curly_balance: int, header: str, lines: list[str]) \
        -> tuple[int, str, str]:
    """
    Extracts a function with multiple lines enclosed by curly braces.
    """
    # { was not closed - search for closing one and
    # assume that this will be the end of the function
    curly_balance = initial_curly_balance
    for j in range(start + 1, len(lines)):
        curly_balance += get_balance(lines[j], "{}")
        # assume that the case where the function ends and then the next { is on the same line is impossible,
        # so it is sufficient to check only at the ends of lines
        if curly_balance == 0:
            body = ''.join((header, *lines[start + 1:j + 1]))
            clean_body = ''.join(lines[start + 1:j + 1]).replace('}', '')
            return j, body, clean_body
    # { was left hanging....
    return len(lines) - 1, '', ''


def get_ident(line: str) -> int:
    """
    Returns the ident of a line in a python file.
    """
    # assume that the code is awesome and jetbrains ides are the best in the world so there are no tabs and only spaces
    return next((i for i in range(len(line)) if line[i] != ' '), 0)


def extract_python_function(start: int, header: str, line: str, lines: list[str]) -> tuple[int, str, str]:
    """
    Extracts a python function.
    """
    ident = get_ident(line)
    j = start
    while j + 1 < len(lines) and get_ident(lines[j + 1]) >= ident + 4:
        j += 1
    body = ''.join((header, *lines[start + 1:j + 1]))
    clean_body = ''.join(lines[start + 1:j + 1])
    return j, body, clean_body


def extract_clean_oneliner(start: int, header: str, line: str) -> tuple[int, str, str]:
    """
    Extracts a one-liner with no curly braces.
    """
    # possible only in kotlin?
    return start, line, line[line.find('=') + 1:]


def process_filename(filename: str) -> tuple[list, int]:
    """
    Returns a list of found methods in the given file and the number of methods missed.
    """
    try:
        missed = 0
        methods = []
        lexer = get_lexer_for_filename(filename)
        with open(filename, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            i = 0
            while i < len(lines):
                line = lines[i]
                for token, s in lexer.get_tokens(line):
                    if token == Token.Name.Function:
                        # name - function name, body - body of the function, clean_body - body without header and braces
                        name, body, clean_body = s, '', ''
                        header = line
                        # function starts on line i
                        # unfortunately only cases consideration here
                        # fixme: ignore parameters on multiple lines for now
                        # fixme: ignore troubles related to comments for now
                        # 1. { is present in the string
                        if '{' in line:
                            # 1.1. { is closed - assume that the function is one-liner
                            curly_balance = get_balance(line, "{}")
                            if curly_balance == 0:
                                i, body, clean_body = extract_curly_oneliner(i, header, line)
                            # 1.2. { not closed - find the closing one
                            elif curly_balance != 0:
                                i, body, clean_body = extract_curly_function(i, curly_balance, header, lines)
                        # 2. line ends with a ':' (python)
                        elif line.strip().endswith(':'):
                            i, body, clean_body = extract_python_function(i, header, line, lines)
                        # 3. line does not end with a ';' or '...' (not a declaration) - assume one-liner and 
                        # parameter list is full
                        elif not line.strip().endswith(';') and \
                                not line.strip().endswith('...') and \
                                get_balance(line, "()") == 0:
                            i, body, clean_body = extract_clean_oneliner(i, header, line)
                        else:
                            # let's count the methods we've missed
                            missed += 1
                            # if get_balance(line, "()") > 0:
                            #     missed += 1
                            # else:
                            #     print(line)
                        if clean_body.strip() != '':
                            methods.append((name, body))
                        break
                i += 1
        return methods, missed
    except (UnicodeDecodeError, ClassNotFound):
        return [], 0


def get_methods(directory: str) -> tuple[list, int]:
    """
    Returns the list of all the methods in a directory and a number of methods missed.
    """
    methods = []
    missed = 0
    files = get_files(directory)
    for file in tqdm.tqdm(files):
        add_methods, add_missed = process_filename(file)
        missed += add_missed
        methods.extend(add_methods)
    return methods, missed


def main():
    # print('\n'.join(get_files(DIR)))
    # print(get_files_by_extension(DIR, ".class")[1])
    # extension_count = get_file_extensions(DIR)
    # print(len(extension_count))
    #
    # print('\n'.join(f"{ext}: {cnt[0]}; e.g. \"{cnt[1]}\"" for ext, cnt in extension_count))
    methods, missed = get_methods(DIR)
    print(f"Missed total of {missed} methods.")
    for name, method in random.sample(methods, 10):
        print(name)
        print(method)

    with open("old/methods.json", 'w') as f:
        json.dump(methods, f)


if __name__ == '__main__':
    main()
