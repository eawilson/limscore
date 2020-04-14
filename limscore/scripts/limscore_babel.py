import importlib
import sys
import os
import subprocess
import pdb

import limscore



def q_(text):
    return f"'{text}'"



def main():
    args = sys.argv
    if len(args) < 2:
        print("Name of package required.", file=sys.stderr)
        sys.exit(1)
    
    module = importlib.import_module(args[1])
    package_path = os.path.dirname(module.__file__)
    
    locales_dir = os.path.join(package_path, "locales")
    if not(os.path.exists(locales_dir)):
        os.mkdir(locales_dir)
    
    pot_path = os.path.join(locales_dir, "{}.pot".format(module.__name__))
    command = ["pybabel",
               "extract", 
               "-o", q_(pot_path),
               q_(package_path),
               q_(os.path.dirname(limscore.__file__))]
    subprocess.run(" ".join(command), shell=True)
    
    for locale in os.listdir(locales_dir):
        locale_dir = os.path.join(locales_dir, locale)
        if os.path.isdir(locale_dir):
            po_path = os.path.join(locale_dir, "LC_MESSAGES", f"{locale}.po")
            command = ["pybabel",
                        "update" if os.path.exists(po_path) else "init", 
                        "-i", q_(pot_path),
                        "-o", q_(po_path),
                        "-l", locale]
            subprocess.run(" ".join(command), shell=True)
     

    
if __name__ == "__main_":
    main()
