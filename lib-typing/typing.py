"""Static type checking helpers"""

from abc import ABCMeta, abstractmethod
import inspect
import sys


__all__ = [
    # Type-related definitions
    'AbstractGeneric',
    'AbstractGenericMeta',
    'Any',
    'ForwardRef',
    'Generic',
    'GenericMeta',
    'Protocol',
    # Utilities
    'cast',
    'overload',
    'typevar',
    # Protocols and abstract base classes
    'Container',
    'Iterable',
    'Iterator',
    'Sequence',
    'Sized',
]


class GenericMeta(type):
    """Metaclass for generic classes that support indexing by types."""
    
    def __getitem__(self, args):
        # Just ignore args; they are for compile-time checks only.
        return self


class Generic(metaclass=GenericMeta):
    """Base class for generic classes."""


class AbstractGenericMeta(ABCMeta):
    """Metaclass for abstract generic classes that support type indexing.

    This is used for both protocols and ordinary abstract classes.
    """
    
    def __new__(mcls, name, bases, namespace):
        cls = super().__new__(mcls, name, bases, namespace)
        # 'Protocol' must be an explicit base class in order for a class to
        # be a protocol.
        cls._is_protocol = name == 'Protocol' or Protocol in bases
        return cls
    
    def __getitem__(self, args):
        # Just ignore args; they are for compile-time checks only.
        return self


class Protocol(metaclass=AbstractGenericMeta):
    """Base class for protocol classes."""

    @classmethod
    def __subclasshook__(cls, c):
        if not cls._is_protocol:
            # No structural checks since this isn't a protocol.
            return NotImplemented
        
        if cls is Protocol:
            # Every class is a subclass of the empty protocol.
            return True

        # Find all attributes defined in the protocol.
        attrs = cls._get_protocol_attrs()

        for attr in attrs:
            if not any(attr in d.__dict__ for d in c.__mro__):
                return NotImplemented
        return True

    @classmethod
    def _get_protocol_attrs(cls):
        # Get all Protocol base classes.
        protocol_bases = []
        for c in cls.__mro__:
            if getattr(c, '_is_protocol', False) and c.__name__ != 'Protocol':
                protocol_bases.append(c)
        
        # Get attributes included in protocol.
        attrs = set()
        for base in protocol_bases:
            for attr in base.__dict__.keys():
                # Include attributes not defined in any non-protocol bases.
                for c in cls.__mro__:
                    if (c is not base and attr in c.__dict__ and
                            not getattr(c, '_is_protocol', False)):
                        break
                else:
                    if (not attr.startswith('_abc_') and
                        attr != '__abstractmethods__' and
                        attr != '_is_protocol' and
                        attr != '__dict__' and
                        attr != '_get_protocol_attrs' and
                        attr != '__module__'):
                        attrs.add(attr)
        
        return attrs


class AbstractGeneric(metaclass=AbstractGenericMeta):
    """Base class for abstract generic classes."""


class TypeAlias:
    """Class for defining generic aliases for library types."""
    
    def __init__(self, target_type):
        self.target_type = target_type
    
    def __getitem__(self, typeargs):
        return self.target_type


# Define aliases for built-in types that support indexing.
List = TypeAlias(list)
Dict = TypeAlias(dict)
Tuple = TypeAlias(tuple)
Function = TypeAlias(callable)


class typevar:
    def __init__(self, name):
        self.name = name


class ForwardRef:
    def __init__(self, name):
        self.name = name


def Any(x):
    """The Any type; can also be used to cast a value to type Any."""
    return x


def cast(type, object):
    """Cast a value to a type.

    This only affects static checking; simply return object at runtime.
    """
    return object


def overload(func):
    """Function decorator for defining overloaded functions."""
    frame = sys._getframe(1)
    locals = frame.f_locals
    if func.__name__ in locals:
        orig_func = locals[func.__name__]
        
        def wrapper(*args, **kwargs):
            ret, ok = orig_func.dispatch(*args, **kwargs)
            if ok:
                return ret
            return func(*args, **kwargs)
        wrapper.isoverload = True
        wrapper.dispatch = make_dispatcher(func, orig_func.dispatch)
        wrapper.next = orig_func
        wrapper.__name__ = func.__name__
        if hasattr(func, '__isabstractmethod__'):
            # Note that we can't reliably check that abstractmethod is
            # used consistently across overload variants, so we let a
            # static checker do it.
            wrapper.__isabstractmethod__ = func.__isabstractmethod__
        return wrapper
    else:
        # Return the initial overload variant.
        func.isoverload = True
        func.dispatch = make_dispatcher(func)
        func.next = None
        return func


def is_erased_type(t):
    return t is Any or isinstance(t, typevar)


def make_dispatcher(func, previous=None):
    """Create argument dispatcher for an overloaded function.

    Also handle chaining of multiple overload variants.
    """
    (args, varargs, varkw, defaults,
     kwonlyargs, kwonlydefaults, annotations) = inspect.getfullargspec(func)
    
    argtypes = []
    for arg in args:
        ann = annotations.get(arg)
        if isinstance(ann, ForwardRef):
            ann = ann.name
        if is_erased_type(ann):
            ann = None
        elif isinstance(ann, str):
            # The annotation is a string => evaluate it lazily when the
            # overloaded function is first called.
            frame = sys._getframe(2)
            t = [None]
            ann_str = ann
            def check(x):
                if not t[0]:
                    # Evaluate string in the context of the overload caller.
                    t[0] = eval(ann_str, frame.f_globals, frame.f_locals)
                    if is_erased_type(t[0]):
                        # Anything goes.
                        t[0] = object
                if isinstance(t[0], type):
                    return isinstance(x, t[0])
                else:
                    return t[0](x)
            ann = check
        argtypes.append(ann)

    maxargs = len(argtypes)
    minargs = maxargs
    if defaults:
        minargs = len(argtypes) - len(defaults)
    
    def dispatch(*args, **kwargs):
        if previous:
            ret, ok = previous(*args, **kwargs)
            if ok:
                return ret, ok

        nargs = len(args)
        if nargs < minargs or nargs > maxargs:
            # Invalid argument count.
            return None, False
        
        for i in range(nargs):
            argtype = argtypes[i]
            if argtype:
                if isinstance(argtype, type):
                    if not isinstance(args[i], argtype):
                        break
                else:
                    if not argtype(args[i]):
                        break
        else:
            return func(*args, **kwargs), True
        return None, False
    return dispatch


# Abstract classes


t = typevar('t')


class Sized(Protocol):
    @abstractmethod
    def __len__(self) -> int: pass


class Container(Protocol[t]):
    @abstractmethod
    def __contains__(self, x) -> bool: pass


class Iterable(Protocol[t]):
    @abstractmethod
    def __iter__(self) -> 'Iterator[t]': pass


class Iterator(Iterable[t], Protocol[t]):
    @abstractmethod
    def __next__(self) -> t: pass


class Sequence(Sized, Iterable[t], Container[t], AbstractGeneric[t]):
    @abstractmethod
    @overload
    def __getitem__(self, i:int) -> t: pass
    
    @abstractmethod
    @overload
    def __getitem__(self, s:slice) -> 'Sequence[t]': pass
    
    @abstractmethod
    def __reversed__(self, s:slice) -> Iterator[t]: pass
    
    @abstractmethod
    def index(self, x) -> int: pass
    
    @abstractmethod
    def count(self, x) -> int: pass


for t in list, tuple, str, bytes, range:
    Sequence.register(t)


del t
