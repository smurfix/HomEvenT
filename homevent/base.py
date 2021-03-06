# -*- coding: utf-8 -*-

##
##  Copyright © 2007-2012, Matthias Urlichs <matthias@urlichs.de>
##
##  This program is free software: you can redistribute it and/or modify
##  it under the terms of the GNU General Public License as published by
##  the Free Software Foundation, either version 3 of the License, or
##  (at your option) any later version.
##
##  This program is distributed in the hope that it will be useful,
##  but WITHOUT ANY WARRANTY; without even the implied warranty of
##  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
##  GNU General Public License (included; see the file LICENSE)
##  for more details.
##

"""\
	This module holds a few random constants and stuff.
	"""

SYS_PRIO = -10
MIN_PRIO = 0
MAX_PRIO = 100

# This construct represents a type as-is
class singleNameMeta(type):
	def __repr__(cls):
		return cls.__name__
class singleName(object):
	__metaclass__ = singleNameMeta

class Name(tuple):
	"""A class that knows how to print itself the "right" way"""
	delim = u"¦"
	prefix = ""
	suffix = ""

	def __new__(cls,*data):
		if len(data) == 1 and isinstance(data[0],tuple):
			data = data[0]
		if len(data) > 0 and not isinstance(data[0],(basestring,int,float)):
			raise RuntimeError("Name:"+repr(data))
		return super(Name,cls).__new__(cls,data)
	def __str__(self):
		return unicode(self).encode("utf-8")
	def __unicode__(self):
		return self.prefix + self.delim.join((unicode(x) for x in self)) + self.suffix
	def __repr__(self):
		return self.__class__.__name__+super(Name,self).__repr__()

	def apply(self, ctx=None, drop=0):
		"""\
			Copy a name, applying substitutions.
			This code dies with an AttributeError if there are no
			matching substitutes. This is intentional.
			"""
		if ctx is None:
			if drop:
				return self.__class__(*self[drop:])
			else:
				return self

		res = []
		for n in self[drop:]:
			if hasattr(n,"startswith") and n.startswith('$'):
				n = getattr(ctx,n[1:])
			res.append(n)
		return self.__class__(*res)
	

	# The following are rich comparison and hashign methods, intended so
	# that one-element names compare identically to the corresponding strings
for s in "hash".split(): ## id
	s="__"+s+"__"
	def gen_id(s):
		def f(self):
			if len(self) == 1:
				return getattr(unicode(self),s)()
			return getattr(super(Name,self),s)()
		f.__name__ = s
		return f
	setattr(Name,s,gen_id(s))
for s in "le lt ge gt eq ne".split(): ## cmp
	s="__"+s+"__"

	def gen_cmp(s):
		def f(self,other):
			if isinstance(other,basestring):
				return getattr(unicode(self),s)(other)
			return getattr(super(Name,self),s)(other)
		f.__name__ = s
		return f
	setattr(Name,s,gen_cmp(s))


def SName(data,attr="name"):
	"""An alternate Name constructor that accepts a single argument"""
	if isinstance(data,Name):
		return data
	n = getattr(data,attr,None)
	if isinstance(n,Name):
		return n

	if isinstance(data,basestring):
		data = data.split(" ")
	return Name(*data)

class RaisedError(RuntimeError):
	"""An error that has been explicitly raised by a script"""
	no_backtrace = True

	def __init__(self,*params):
		self.params = params
	def __repr__(self):
		return u"‹%s: %s›" % (self.__class__.__name__, repr(self.params))
	def __str__(self):
		return u"%s: %s" % (self.__class__.__name__, " ".join(str(x) for x in self.params))
	def __unicode__(self):
		return u"%s: %s" % (self.__class__.__name__, " ".join(unicode(x) for x in self.params))


def flatten(out,s,p=""):
	if hasattr(s,"list") and callable(s.list):
		for ss in s.list():
			flatten(out,ss,p)
		return
	s = list(s)
	t = s.pop()
	if p != "":
		s.insert(0,p)
	p = u" ".join((str(ss) for ss in s))
	if hasattr(t,"list") and callable(t.list):
		t = t.list()
	if hasattr(t,"next"):
		pp = " "*len(p)
		for tt in t:
			flatten(out,tt,p)
			p = pp
	else:
		out.put((p,t))

