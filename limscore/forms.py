import re, pdb
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from collections import OrderedDict
from collections.abc import MutableMapping
from itertools import chain

from html import escape
from jinja2 import Markup
from flask import session


email_regex = re.compile("^[a-zA-Z0-9.!#$%&'*+\/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$")
name_regex = re.compile("[^a-zA-Z-' ]")
number_regex = re.compile("^[0-9]+$")



def is_valid_nhs_number(data):
    if len(data) == 10 and data.isnumeric():
        val = 11 - (sum(int(x)*y for x, y in zip(data[:9], range(10, 1, -1))) % 11)
        if val == 11:
            val = 0
        if val == int(data[9]):
            return data



class Fields(MutableMapping):
    """Ordered collection of form fields that can be accessed by name, either as an attribute or key.
       Names will be converted to string before being saved. None and "" are both illegal and will raise a TypeError.
       May be initialised with a variable number of (name, field) tuples or with name=field passed as keyword arguments.
       Each field added will have its name and id html attributes set to its name.
    """
    def __init__(self, *args, **kwargs):
        super().__init__()
        super().__setattr__("_dict", {})
        super().__setattr__("_list", [])
        for key, val in args+tuple(kwargs.items()):
            self.__setitem__(key, val)
        
    
    def __repr__(self):
        return "{}({})".format(type(self).__name__, repr(self._dict))
        
        
    def __getitem__(self, key):
        return self._dict[key]
        
        
    def __setitem__(self, key, val):
        if key in ("", None):
            raise TypeError('{} is not a legal name for a field.'.format(repr(key)))
        key = str(key)
        self._dict[key] = val
        val.attr["name"] = key
        val.attr["id"] = key
        if key not in self._list:
            self._list.append(key)
        
        
    def __delitem__(self, key):
        del self._dict[key]
        self._list.remove(key)
        
    
    def __iter__(self):
        yield from self._list
        
        
    def __len__(self):
        return len(self._dict)
    
        
    def __getattr__(self, attr):
        try:
            return super().__getattr__(attr)
        except AttributeError:
            try:
                return self.__getitem__(attr)
            except KeyError:
                msg = "{} object has no attribute {}".format(type(self).__name__, attr)
                raise AttributeError(msg)
        
        
    def __setattr__(self, attr, val):
        return self.__setitem__(attr, val)
    
    
    def __delattr__(self, attr):
        try:
            return super().__delattr__(attr)
        except AttributeError:
            try:
                return self.__delitem__(attr)
            except KeyError:
                msg = "{} object has no attribute {}".format(type(self).__name__, attr)
                raise AttributeError(msg)
    


class Form(Fields):
    def __init__(self, data=None, **kwargs):
        super().__init__()
        self.definition()
        self.fill(data, **kwargs)        
    
    
    def __repr__(self):
        return "{}({})".format(type(self).__name__, ", ".join([repr(field) for field in self.values()]))
    
    
    def fill(self, data=None, **kwargs):
        if data:
            for name, field in self.items():
                if field.empty == list and hasattr(data, "getlist"):
                    field.data = data.getlist(name)
                elif name in data:
                    field.data = data.get(name)
                    
        for k, v in kwargs.items():
            if k.endswith("_choices") and k[:-8] in self:
                self[k[:-8]].choices = v
            else:
                raise TypeError("Unknown keyword argument {}.".format(k))


    @property
    def fields(self):
        return self.values()
    
    
    def definition(self):
        return
        
        
    def validate(self):
        return all(field.validate() for field in self.values())
    
    
    @property
    def errors(self):
        return any(field.errors for field in self.values())
    
    
    @property
    def data(self):
        return {name: field.data for name, field in self.items()}


    @property
    def csrf(self):
        return session["csrf"]



class HTMLAttr(MutableMapping):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.attr = {}
        for d in args + (kwargs,):
            for k, v in d.items():
                self.__setitem__(k, v)
                

    def __setitem__(self, k, v):
        if k.startswith("_"):
            k = k[1:]
        if k == "class" and "class" in self:
            v = "{} {}".format(self["class"], v)
        self.attr.__setitem__(k, v)
    
    
    def __repr__(self):
        return "{}({})".format(type(self).__name__, repr(self.attr))


    def __str__(self):
        attr = []
        for k, v in sorted(self.items()):
            if v is True:
                attr.append(k)
            elif v is not False and v is not None and v != "":
                attr.append('{}="{}"'.format(k, escape(str(v))))
        return " ".join(attr)
    
    
    def __getitem__(self, k):
        return self.attr.__getitem__(k)
    
    
    def __delitem__(self, k):
        return self.attr.__delitem__(k)
    
    
    def __iter__(self):
        return self.attr.__iter__()
    
    
    def __len__(self):
        return self.attr.__len__()
            

    
class Input(object):
    empty = type(None)
    
    def __init__(self, label="", required=True, **kwargs):
        self.attr = HTMLAttr(**kwargs)
        self._label = label
        self.required = required
        self.data = self.empty()
        self.errors = ""
    
    
    def __repr__(self):
        return "{}({}, value={})".format(type(self).__name__, ", ".join("{}={}".format(k, v) for k, v in self.attr.items()), repr(self.data)) 
    
    
    @property
    def data(self):
        return self._data
            
            
    @data.setter
    def data(self, val):
        if hasattr(val, "strip"):
            val = val.strip()
        self._data = self.empty() if val in (None, "") else self.convert(val)
    
    
    def convert(self, val):
        return str(val)
    
    
    def validate(self):
        if (self.data == self.empty()) and self.required:
            self.errors = "Data required."
        return not self.errors
   
    
    def label(self, **kwargs):
        return Markup('<label {}>{}</label>'.format(HTMLAttr(kwargs, _for=self.attr["id"]), escape(self._label)))
    
    
    def __call__(self, **kwargs):
        return Markup('<input {}>'.format(HTMLAttr(self.attr, kwargs, value=self.data)))



class TextInput(Input):
    empty = str
        
        
        
class HiddenInput(TextInput):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, _type="hidden", **kwargs)



class TextAreaInput(TextInput):
    def __init__(self, *args, rows="1", **kwargs):
        super().__init__(*args, rows=rows, **kwargs)

    def __call__(self, **kwargs):
        return Markup('<textarea {}>{}</textarea>'.format(HTMLAttr(self.attr, kwargs), escape(self.data if self.data not in (None, "") else "")))



class PasswordInput(Input):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, _type="password", **kwargs)
    
    def __call__(self, **kwargs):
        return Markup('<input {}>'.format(HTMLAttr(self.attr, kwargs)))
        
        

class NameInput(Input):
    def validate(self):
        if super().validate() and self.data:
            invalid_chars = "".join(name_regex.findall(self.data))
            if invalid_chars:
                self.errors = "Invalid character{} {} in name.".format("s" if len(invalid_chars)>1 else "", repr(invalid_chars))
        return not self.errors



class TextNumberInput(Input):
    def validate(self):
        if super().validate() and self.data and not number_regex.match(self.data):
            self.errors = "Must be a number."
        return not self.errors



class LowerCaseInput(Input):
    def convert(self, val):
        return val.lower()



class NHSNumberInput(Input):
    def validate(self):
        if super().validate() and self.data and not is_valid_nhs_number(self.data):
            self.errors = "Not a valid NHS number."
        return not self.errors
    
    def convert(self, val):
        self._data = "".join(val.split())



class EmailInput(LowerCaseInput):
    def validate(self):
        if super().validate() and self.data and not email_regex.match(self.data):
            self.errors = "Invalid email address."
        return not self.errors



class IntegerInput(Input):
    def __init__(self, *args, minval=None, maxval=None, **kwargs):
        self.minval=minval
        self.maxval = maxval
        super().__init__(*args, **kwargs)
    
    def convert(self, val):
        try:
            return int(val)
        except (ValueError, TypeError):
            self.errors = "Not a valid integer."

    def validate(self):
        if super().validate() and self.data != self.empty():
            if self.minval is not None and self.data < self.minval:
                self.errors = "Cannot be less than {}.".format(self.minval)
            if self.maxval is not None and self.data > self.maxval:
                self.errors = "Cannot be greater than {}.".format(self.maxval)
        return not self.errors
    


class DecimalInput(Input):
    def __init__(self, *args, prec=1, **kwargs):
        self.prec = prec
        super().__init__(*args, **kwargs)
    
    def convert(self, val):
        try:
            return Decimal(val).quantize(Decimal("".join(["1."]+(["0"]*self.prec)))) # looks crazy but is recommended way to round a decimal from python docs.
        except InvalidOperation:
            self.errors = "Not a valid decimal."



class DateInput(Input):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, _type="date", **kwargs)
    
    
    def convert(self, val):
        if not isinstance(val, date):
            try:
                return datetime.strptime(val, "%Y-%m-%d").date()
            except ValueError:
                self.errors = "Not a valid date."


    def __call__(self, **kwargs):
        return Markup('<input {}>'.format(HTMLAttr(self.attr, kwargs, value=self.data.strftime("%Y-%m-%d") if self.data is not None else "")))



class PastDateInput(DateInput):
    def validate(self):
        if super().validate() and self.data:
            if self.data > datetime.now().date():
                self.errors = "Date cannot be in the future."
        return not self.errors



class BooleanInput(Input):
    empty = bool

    def __init__(self, *args, **kwargs):
        super().__init__(*args, type="checkbox", _class="no-border-focus", **kwargs)
        
    
    def convert(self, val):
        return bool(val)

    
    def __call__(self, **kwargs):
        return Markup('<input {}>'.format(HTMLAttr(self.attr, kwargs, checked=self.data)))



class SelectInput(Input):
    def __init__(self, *args, choices=(), coerce=int, empty_choice=True, **kwargs):
        self._empty_choice = empty_choice
        self.choices = choices
        self.coerce = coerce
        super().__init__(*args, **kwargs)


    @property
    def choices(self):
        return self._choices
    
    
    @choices.setter
    def choices(self, choices):
        if self._empty_choice:
            choices = list(chain(((self.empty(), ""),), choices))
        self._choices = choices
    
    
    def convert(self, val):
        try:
            return self.coerce(val)
        except Exception:
            return self.empty()
        
    
    def validate(self):
        if super().validate():
            try:
                index = [choice[0] for choice in self.choices].index(self.data) # will raise ValueError if not a valid option
            except ValueError:
                self.errors = "Invalid choice."
        return not self.errors


    def __call__(self, **kwargs):
        html = ["<select {}>".format(HTMLAttr(self.attr, kwargs))]
        for choice in self.choices:
            k = choice[0]
            html.append('<option value="{}"{}>{}</option>'.format(escape(str(k) if k is not None else ""), " selected" if self.is_selected(k) else "", escape(str(choice[1]))))
        html.append("</select>")
        return Markup("".join(html))
    
    
    def is_selected(self, option):
        return (option == self.data) or ""



class MultiSelectInput(SelectInput):
    empty = list
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, multiple=True, empty_choice=False, **kwargs)

    
    def validate(self):
        choices = [choice[0] for choice in self.choices]
        try:
            self.data = [self.coerce(data) for data in self.data] # If fails could raise any exception dependent on coerce                
            index = [choices.index(data) for data in self.data] # will raise ValueError if not a valid option
        except Exception:
            self.errors = "Invalid choice."
        if self.required and not self.data:
            self.errors = "Data required."
        return not self.errors


    def convert(self, val):
        return [self.coerce(item) for item in val]


    def is_selected(self, option):
        return (option in self.data) or ""



class MultiCheckboxInput(MultiSelectInput):
    def __iter__(self):
        name = self.attr["name"]
        for index, choice in enumerate(self.choices):
            kwargs = dict(name=name, _id="{}-{}".format(name, index), _type="checkbox", _class="no-border-focus", label=choice[1], checked=self.is_selected(choice[0]))
            if len(choice) > 2 and choice[2] == "disabled":
                kwargs["disabled"] = True
            field = Input(**kwargs)
            field.data = choice[0]
            field.errors = self.errors
            yield field
    
    def legend(self, **kwargs):
        return Markup('<legend {}>{}</legend>'.format(HTMLAttr(kwargs), escape(self._label)))



#############################################################################################################################################################    



class LoginForm(Form):
    def definition(self):
        self.username = LowerCaseInput("Username or Email")
        self.password = PasswordInput("Password", required=False)



class ChangePasswordForm(Form):
    def definition(self):        
        self.old_password = PasswordInput('Old Password', autocomplete="new-password")
        self.password1 = PasswordInput('New Password', autocomplete="new-password")
        self.password2 = PasswordInput('New Password', autocomplete="new-password")

    def validate(self):
        if super().validate() and self.password1.data != self.password2.data:
            self.password1.errors = "Passwords must match."
        return not self.errors


    
class UserEditForm(Form):
    def definition(self):
        self.username = LowerCaseInput("Username", autocomplete="new-password")
        self.surname = TextInput("Surname")
        self.forename = TextInput("Forename")        
        self.email = EmailInput("Email")
        self.password = PasswordInput('Password', autocomplete="new-password")
        self.group_id = MultiCheckboxInput("Groups")



class ReorderForm(Form):
    def definition(self):
        self.order = HiddenInput(required=False)
            

