# Licensed under a 3-clause BSD style license - see LICENSE.rst
# -*- coding: utf-8 -*-

"""
This file manages a transient representation of the tree made up of
simple Python data types (lists, dicts, scalars) wrapped inside of
`Tagged` subclasses, which add a ``tag`` attribute to hold the
associated YAML tag.

Below "basic data types" refers to the basic built-in data types
defined in the core YAML specification.  "Custom data types" are
specialized tags that are added by ASDF or third-parties that are not
in the YAML specification.

When YAML is loaded from disk, we want to first validate it using JSON
schema, which only understands basic Python data types, not the
``Nodes`` that ``pyyaml`` uses as its intermediate representation.
However, basic Python data types do not preserve the tag information
from the YAML file that we need later to convert elements to custom
data types.  Therefore, the approach here is to wrap those basic types
inside of `Tagged` objects long enough to run through the jsonschema
validator, and then convert to custom data types and throwing away the
tag annotations in the process.

Upon writing, the custom data types are first converted to basic
Python data types wrapped in `Tagged` objects.  The tags assigned to
the ``Tagged`` objects are then used to write tags to the YAML file.

All of this is an implementation detail of the our custom YAML loader
and dumper (``yamlutil.AsdfLoader`` and ``yamlutil.AsdfDumper``) and
is not intended to be exposed to the end user.
"""

from __future__ import absolute_import, division, unicode_literals, print_function

import six

from .compat import UserDict, UserList, UserString

__all__ = ['tag_object', 'get_tag']


class Tagged(object):
    """
    Base class of classes that wrap a given object and store a tag
    with it.
    """
    pass


class TaggedDict(Tagged, UserDict, dict):
    """
    A Python dict with a tag attached.
    """
    flow_style = None
    property_order = None

    def __init__(self, data=None, tag=None):
        if data is None:
            data = {}
        self.data = data
        self._tag = tag

    def __eq__(self, other):
        return (isinstance(other, TaggedDict) and
                self.data == other.data and
                self._tag == other._tag)


class TaggedList(Tagged, UserList, list):
    """
    A Python list with a tag attached.
    """
    flow_style = None

    def __init__(self, data=None, tag=None):
        if data is None:
            data = []
        self.data = data
        self._tag = tag

    def __eq__(self, other):
        return (isinstance(other, TaggedList) and
                self.data == other.data and
                self._tag == other._tag)


class TaggedString(Tagged, UserString, six.text_type):
    """
    A Python list with a tag attached.
    """
    style = None

    def __eq__(self, other):
        return (isinstance(other, TaggedString) and
                six.text_type.__eq__(self, other) and
                self._tag == other._tag)


def tag_object(tag, instance, ctx=None):
    """
    Tag an object by wrapping it in a ``Tagged`` instance.
    """
    if isinstance(instance, Tagged):
        instance._tag = tag
    elif isinstance(instance, dict):
        instance = TaggedDict(instance, tag)
    elif isinstance(instance, list):
        instance = TaggedList(instance, tag)
    elif isinstance(instance, six.string_types):
        instance = TaggedString(instance)
        instance._tag = tag
    else:
        from . import AsdfFile, yamlutil
        if ctx is None:
            ctx = AsdfFile()
        try:
            instance = yamlutil.custom_tree_to_tagged_tree(instance, ctx)
        except TypeError:
            raise TypeError("Don't know how to tag a {0}".format(type(instance))) 
        instance._tag = tag
    return instance


def get_tag(instance):
    """
    Get the tag associated with the instance, if there is one.
    """
    return getattr(instance, '_tag', None)
