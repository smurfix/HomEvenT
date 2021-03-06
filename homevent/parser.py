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
This code parses input lines.

By itself, it understands nothing whatsoever.

See the homevent.config module and the test/parser.py script
for typical usage.

"""

from zope.interface import implements
from homevent.tokize import tokizer
from tokenize import tok_name
import Queue
import sys
import os
import errno
from twisted.internet import reactor,threads,defer,interfaces
from twisted.protocols.basic import LineOnlyReceiver,FileSender,_PauseableMixin

import gevent
from gevent.select import select
from gevent.event import AsyncResult

from homevent.geventreactor import waitForDeferred,deferToGreenlet
from homevent.logging import log,TRACE,DEBUG
from homevent.context import Context
from homevent.io import Outputter,conns
from homevent.event import Event,StopParsing
from homevent.statement import global_words
from homevent.twist import deferToLater,setBlocking, fix_exception,print_exception,reraise,Jobber
from homevent.collect import Collection,Collected

class ParseReceiver(Outputter):
	"""This is a mixin to feed a parser"""
	implements(interfaces.IHalfCloseableProtocol)
	delimiter = '\n'

	def __init__(self, parser=None, *a,**k):
		super(ParseReceiver,self).__init__(*a,**k)
		if parser is None:
			from homevent.interpreter import InteractiveInterpreter

			def reporter(err):
				print >>sys.stderr,"Error:",err
			c=Context()
			#c.logger=parse_logger
			i = InteractiveInterpreter(ctx=c)
			parser = Parser(interpreter=i, input=StdIO, ctx=c)
		self.parser = parser
		parser.registerProducer(self,False)
		#parser.startParsing()
	
	def readConnectionLost(self):
		try:
			rl = super(ParseReceiver,self).readConnectionLost
		except AttributeError:
			pass
		else:
			rl()
		if self.parser:
			self.parser.endConnection()
			self.parser = None
		
	def connectionLost(self,reason):
		self.readConnectionLost()
		self.writeConnectionLost()

	def writeConnectionLost(self):
		try:
			rl = super(ParseReceiver,self).writeConnectionLost
		except AttributeError:
			super(ParseReceiver,self).connectionLost("unknown")
		else:
			rl()

	def lineReceived(self, data):
		self.parser.lineReceived(data)
	
	def makeConnection(self,transport):
		assert self.parser is not None, "Need to set the parser"
		if "out" not in self.parser.ctx:
			self.parser.ctx.out = transport

		super(ParseReceiver,self).makeConnection(transport)

	def connectionMade(self):
		super(ParseReceiver,self).connectionMade()
		self.parser.run()
		self.parser.do_prompt = self.parser.proc.do_prompt

def parser_builder(cls=None,protocol=None,interpreter=None,*a,**k):
	"""\
		Return something that builds a receiver class when called with
		no arguments
		"""
	if cls is None:
		cls = LineOnlyReceiver
		impl = interfaces.IPushProducer
	else:
		impl = None
	try:
		ctx = k.pop("ctx")
	except KeyError:
		ctx = Context
	if interpreter is None:
		from homevent.interpreter import InteractiveInterpreter
		interpreter = InteractiveInterpreter

	class mixer(ParseReceiver,cls):
		if impl:
			implements(impl)
		pass

	def gen_builder(*x,**y):
		c = ctx()
		k["ctx"] = c
		i = interpreter(ctx=c)
		p = TwistedParser(interpreter=i, protocol=protocol, ctx=c)

		m = mixer(p, *x,**y)
		return m
	return gen_builder


class Parsers(Collection):
	name = "parser"
	prio = -99
Parsers = Parsers()
Parsers.does("del")
_npars = 0

class Parser(Collected,Jobber):
	"""The input parser object. It is a consumer of lines."""
	storage = Parsers.storage
	line = None
	p_gen = None
	do_prompt = False
	last_pos = None
	job = None

	def __init__(self, input, interpreter, ctx=None):
		"""Parse an input stream and pass the commands to the processor @proc."""
		global _npars
		_npars += 1
		super(Parser,self).__init__("n"+str(_npars))

		self.ending = False

		if ctx is None:
			self.ctx = Context()
		else:
			self.ctx = ctx

		if "filename" not in self.ctx:
			self.ctx.filename=u"‹stdin?›"
		self.input = input
		self.proc = interpreter
		self.do_prompt = interpreter.do_prompt

	def list(self):
		"""Yield a couple of (left,right) tuples, for enumeration."""
		for x in super(Parser,self).list():
			yield x
		yield ("input",str(self.input))
		if self.last_pos is not None:
			yield ("line",str(self.last_pos[0]))
			yield ("pos",str(self.last_pos[1]))

	def info(self):
		return str(self.input)

	def stop_client(self):
		"""Helper. See TwistedParser.stop_client()."""
		pass

	def lineReceived(self, data):
		return self.add_line(data)

	def run(self):
		self.init_state()
		self.prompt()
		if self.input is None:
			self.p_gen = tokizer(self._do_parse,self.job,self.stop_client)
			return
		syn = AsyncResult()
		self.start_job("job",self._run,syn)
		self.p_gen = tokizer(self._do_parse,self.job)
		syn.set(None)

		try:
			e = self.job.get()
			if isinstance(e,BaseException):
				reraise(e)
		except StopParsing:
			pass

		self.p_gen.exit()
		
	def _run(self,syn):
		syn.get()
		try:
			setBlocking(False,self.input)
			while True:
				try:
					l = self.input.readline()
				except EnvironmentError as e:
					fix_exception(e)
					if e.errno != errno.EAGAIN or not hasattr(self.input,"fileno"):
						raise
					r,_,_ = select((self.input,),(),())
					if not r:
						return
					continue
	
				if not l:
					break
				self.add_line(l)
		
		except BaseException as e:
			fix_exception(e)
			return e
		finally:
			setBlocking(True,self.input)

			job = gevent.spawn(self.endConnection,kill=False)
			def dead(e):
				fix_exception(e)
				process_failure(e)
			job.link_exception(dead)
			if not hasattr(self.input,"fileno") or self.input.fileno() > 2:
				self.input.close()
			self.input = None
		return "Bla"
	

	def endConnection(self, res=None, kill=True):
		"""Called to stop"""
		if self.job:
			if kill:
				self.p_gen.exit()
				self.stop_job("job")
			else:
				self.p_gen.feed(None)

	def delete(self,ctx=None):
		self.endConnection()
		super(Parser,self).delete()

	def add_line(self, data):
		"""Standard LineReceiver method"""
		if not isinstance(data,unicode):
			data = data.decode("utf-8")
		self.p_gen.feed(data)

	def init_state(self):
		self.p_state=0
		self.p_pop_after=False
		self.p_stack = []
		self.p_args = []
		if self.p_gen:
			self.p_gen.init()

	def prompt(self):
		if not self.do_prompt:
			return
		if self.p_state == 0 and not self.p_stack:
			self.ctx.out.write(">> ")
		else:
			self.ctx.out.write(".. ")
		getattr(self.ctx.out,"flush",lambda :None)()

	def _do_parse(self, t,txt,beg,end,line):
		# States: 0 newline, 1 after first word, 2 OK to extend word
		#         3+4 need newline+indent after sub-level start, 5 extending word
		#log("parser",TRACE,"PARSE",t,repr(txt))

		try:
			res = self._parseStep(t,txt,beg,end,line)
			if isinstance(res,defer.Deferred):
				waitForDeferred(res)

		except StopIteration:
			return

		except Exception as ex:
			fix_exception(ex)
			if self.p_stack:
				self.proc = self.p_stack[0]

			self.proc.error(self,ex)
			self.prompt()

	def _parseStep(self, t,txt,beg,end,line):
		from token import NUMBER,NAME,DEDENT,INDENT,OP,NEWLINE,ENDMARKER, \
			STRING
		from homevent.tokize import COMMENT,NL
		self.last_pos = beg

		if "logger" in self.ctx:
			self.ctx.logger("T",self.p_state,t,repr(txt),beg,end,repr(line))
		if t == COMMENT:
			return
		if self.p_state == 0: # begin of statement
			if t == NAME:
				self.p_args = [txt]
				self.p_state=1
				return
			elif t == DEDENT:
				self.proc.done()
				if self.p_stack:
					self.proc = self.p_stack.pop()
					return
				else:
					raise StopIteration
			elif t == ENDMARKER:
				self.proc.done()
				while self.p_stack:
					self.proc = self.p_stack.pop()
					self.proc.done()
				raise StopIteration
			elif t in(NL,NEWLINE):
				self.prompt()
				return
			elif t == OP and txt == ".":
				return # "I am done"
		elif self.p_state in (1,2): # after first word
			if t == NAME:
				self.p_args.append(txt)
				self.p_state = 2
				return
			elif t == OP and txt in ("*","+","-"):
				self.p_args.append(txt)
				self.p_state = 1
				return
			elif t == NUMBER:
				self.p_args.append(eval(txt,{},{}))
				self.p_state = 1
				return
			elif t == STRING:
				self.p_args.append(eval(txt,{},{}))
				self.p_state = 1
				return
			elif t == OP and txt[0] in ("$","*"):
				self.p_args.append(txt)
				self.p_state = 1
				return
			elif t == OP and txt == "." and self.p_state == 2:
				self.p_state = 5
				return
			elif t == OP and txt == ":":
				log("parser",TRACE,"RUN2")
				log("parser",TRACE,self.proc.complex_statement,self.p_args)
				self.p_state = 3
				_ = waitForDeferred(self.proc.complex_statement(self.p_args))

				self.p_stack.append(self.proc)
				self.proc = _
				return
			elif t == NEWLINE:
				log("parser",TRACE,"RUN3")
				log("parser",TRACE,self.proc.simple_statement,self.p_args)
				# defer setting state to zero when pop_after is set
				# because that would break one-line compound statements
				# ("wait :for 2").
				# On the other hand, setting it later anyway breaks
				# statements which terminate the parser ("exit")
				if not self.p_pop_after:
					self.p_state=0
				waitForDeferred(self.proc.simple_statement(self.p_args))
					
				if self.p_pop_after:
					self.proc.done()
					self.proc = self.p_stack.pop()
					self.p_pop_after=False
					self.p_state=0
				self.prompt()
				return
		elif self.p_state == 3:
			if t == NEWLINE:
				self.p_state = 4
				self.prompt()
				return
			elif t == NAME:
				self.p_args = [txt]
				self.p_state = 1
				self.p_pop_after = True
				return
			else:
				self.proc = self.p_stack.pop()
		elif self.p_state == 4:
			if t == INDENT:
				self.p_state = 0
				return
			elif t == NEWLINE:
				# ignore
				return
			else:
				self.proc = self.p_stack.pop()
		elif self.p_state == 5:
			if t == NAME:
				self.p_args[-1] += "."+txt
				self.p_state = 2
				return

		if self.p_pop_after:
			self.proc = self.p_stack.pop()
			self.p_pop_after = False

		raise SyntaxError("Unknown token %s (%s, state %d) in %s:%d" % (repr(txt),tok_name[t] if t in tok_name else t,self.p_state,self.ctx.filename,beg[0]))


class TwistedParser(Parser,LineOnlyReceiver,object):
	delimiter = "\n"

	def __init__(self, protocol, interpreter, ctx=None):
		self.protocol = protocol
		super(TwistedParser,self).__init__(input=None,interpreter=interpreter,ctx=ctx)

	def lineReceived(self, data):
		log("parser",TRACE,"S LINE",repr(data))
		return deferToGreenlet(self.add_line,data+"\n")
	
	def write(self, data):
		log("parser",TRACE,"S WRITE",self.transport,repr(data))
		self.dataReceived(data)
	
	def registerProducer(self, producer, streaming):
		log("parser",TRACE,"S START")
		self.producer = producer
		self.streaming = streaming
	
	def unregisterProducer(self):
		log("parser",TRACE,"S STOP")
		self.producer = None
		self.delete()
	
	def stop_client(self):
		"""Helper when the client types "exit" or whatever."""
		self.producer.loseConnection()
		self.delete()

class _drop(object):
	def __init__(self,g):
		self.g = g
		self.lost = False
		conns.append(self)
	def loseConnection(self):
		self.lost = True
		log("parser",DEBUG,"LAST_SYM _drop")
	def drop(self,_):
		log("parser",DEBUG,"LAST_SYM drop")
		conns.remove(self)
		self.loseConnection()
		return _

def parse(input, interpreter=None, ctx=None, out=None, words=None):
	"""\
		Read non-blocking input, run through the tokenizer, pass to the
		parser.
		"""
	if ctx is None: ctx=Context
	if ctx is Context or "filename" not in ctx:
		ctx = ctx(filename=(input if isinstance(input,basestring) else u"‹stdin›"))
	if out is not None:
		ctx.out = out
	else:
		ctx.out = sys.stdout
		if "words" not in ctx:
			if words is None: words = global_words(ctx)
			ctx.words = words

	if interpreter is None:
		from homevent.interpreter import Interpreter
		interpreter = Interpreter
	if isinstance(interpreter,type):
		interpreter = interpreter(ctx)

	if isinstance(input,basestring):
		input = open(input,"rU")

	parser = Parser(interpreter=interpreter, input=input, ctx=ctx)
	parser.run()
	
