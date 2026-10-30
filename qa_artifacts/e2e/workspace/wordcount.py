import sys

def main():
    if len(sys.argv) != 2:
        print('usage: wordcount.py FILE')
        sys.exit(2)
    file_path = sys.argv[1]
    try:
        with open(file_path, 'r') as file:
            text = file.read()
            words = text.split()
            print(f'words: {len(words)}')
    except FileNotFoundError:
        print(f'error: file not found: {file_path}')
        sys.exit(2)

if __name__ == '__main__':
    main()