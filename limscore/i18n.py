import os
import glob
import csv
import pdb
import importlib

from flask import current_app, session, request
from babel.messages.pofile import read_po
    

def _(text):
    try:
        print(text)
        return current_app.extensions["locales"][session["locale"]][text]
    except KeyError:
        return text



def i18n_init(app):
    package = importlib.import_module(app.import_name)
    root_dir = os.path.dirname(package.__file__)
    locales_dir = os.path.join(root_dir, "locales")
    if not os.path.exists(locales_dir):
        return
    
    translations = {}
    app.extensions["locales"] = translations
    for locale in os.listdir(locales_dir):        
        po_file = os.path.join(locales_dir, locale, "LC_MESSAGES", f"{locale}.po")
        if os.path.exists(po_file):
            with open(po_file) as f:
                catalog = read_po(f)
                
            translations[locale] = {}
            for message in catalog:
                if message.id and message.string:
                    translations[locale][message.id] = message.string
                                
    if "en_GB" not in translations:
        translations["en_GB"] = {}
    
    

def locale_from_headers():
    # en-GB,en-US;q=0.9,en;q=0.8
    languages = request.headers.get("Accept-Language", "")
    return "en_GB"
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
