from pytz import timezone
from flask import session


class Local(object):
    """ Wrapper around a datetime object thar will print in local time with
        the specified formatstring. Also has a value property which is used
        to provide a data-sort value to sortable tables.
    """
    def __init__(self, val, formatstring="%d %b %Y %H:%M"):
        self._val = val
        self._formatstring = formatstring
        
    def __repr__(self):
        return "{}({})".format(type(self).__name__, repr(self._val))
    
    def __str__(self):
        if self._val is None:
            return ""
        tz = timezone(session["timezone"])
        return self._val.astimezone(tz).strftime(self._formatstring)
    
    def __html__(self):
        return self.__str__()
    
    @property
    def value(self):
        if self._val is None:
            return ""
        return self._val.timestamp() 



class Attr(object):
    """ Wrapper around any object passed to a template that will allow the
        the optional addition of additional attributes to control
        formatting.
    """
    def __init__(self, val, **kwargs):
        self._val = val
        self._kwargs = kwargs
     
    def __repr__(self):
        kwargs = ", {}".format(repr(self._kwargs)) if self._kwargs else ""
        return "{}('{}'{})".format(type(self).__name__, str(self._val), kwargs)
           
    def __str__(self): 
        return str(self._val)
    
    def __getattr__(self, attr):
        try:
            return self._kwargs[attr]
        except KeyError:
            msg = "'{}' object has no attribute '{}'"
            raise AttributeError(msg.format(type(self).__name__, attr))
