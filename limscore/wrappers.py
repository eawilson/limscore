from pytz import timezone
from babel.dates import format_datetime
from flask import session



class Local(object):
    """ Wrapper around a datetime object thar will print in local time with
        the specified format. Also has a value property which is used
        to provide a data-sort value to sortable tables.
    """
    def __init__(self, val, format="medium"):
        self._val = val
        self._format = format
        
    def __repr__(self):
        return "{}({}, format='{}')".format(type(self).__name__,
                                            repr(self._val),
                                            self._format)
    
    def __html__(self):
        if self._val is None:
            return ""
        tz = timezone(session["timezone"])
        dt = self._val.astimezone(tz)
        ret = format_datetime(dt, 
                              format=self._format,
                              locale=session["locale"])
        if self._format != "long":
            ret = "{} {}".format(ret, dt.strftime("%Z"))
        return ret
    
    def __str__(self):
        return self.__html__()
    
    @property
    def value(self):
        if self._val is None:
            return ""
        return self._val.timestamp() 



class Attr(object):
    """ Wrapper around any object passed to a template that will allow the
        the optional addition of additional attributes to control
        formatting and sorting.
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



#class Number(object):
    #""" Wrapper around any object passed to a template that will allow the
        #the optional addition of additional attributes to control
        #formatting and sorting.
    #"""
    #def __init__(self, val):
        #self._val = val
     
    #def __repr__(self):
        #return "{}({})".format(type(self).__name__, str(self._val))
           
    #def __str__(self): 
        #return str(self._val)
    
    #def __getattr__(self, attr):
        #try:
            #return self._kwargs[attr]
        #except KeyError:
            #msg = "'{}' object has no attribute '{}'"
            #raise AttributeError(msg.format(type(self).__name__, attr))
