#!/usr/bin/python
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

from homevent.interpreter import InteractiveInterpreter,Interpreter
from homevent.parser import parse
from homevent.statement import main_words, global_words
from homevent.check import register_condition
from homevent.module import load_module, Load,LoadDir
from homevent.reactor import ShutdownHandler,mainloop,shut_down
from homevent.context import Context
from homevent.twist import callLater,fix_exception
from homevent.geventreactor import waitForDeferred

from twisted.internet import reactor,interfaces,fdesc
from twisted.internet._posixstdio import StandardIO ## XXX unstable interface!
from twisted.internet.error import ConnectionDone,ConnectionLost
from tokenize import tok_name
import os,sys

main_words.register_statement(Load)
main_words.register_statement(LoadDir)
main_words.register_statement(ShutdownHandler)

load_module("help")
load_module("data")
load_module("file")
load_module("path")
load_module("ifelse")

syms = {}
def parse_logger(t,*x):
	x=list(x)
	try:
		x[1] = tok_name[x[1]]
	except KeyError:
		pass
	print t+":"+" ".join(str(d) for d in x)

class StdIO(StandardIO):
	def __init__(self,*a,**k):
		super(StdIO,self).__init__(*a,**k)
		fdesc.setBlocking(self._writer.fd)
	def connectionLost(self,reason):
		super(StdIO,self).connectionLost(self)
		if not reason.check(ConnectionDone,ConnectionLost):
			print "EOF:",reason
	def write(self,data):
		sys.stdout.write(data)
	def flush(self):
		sys.stdout.flush()

def reporter(err):
	print "Error:",err
	
def looper():
	while True:
		print "L"
		sleep(1)

def ready():
	c=Context()
	for f in sys.argv[1:]:
		read_config(c,f)
		parse(f, interpreter, ctx=c)
	
	#c.logger=parse_logger
	if os.isatty(0):
		i = InteractiveInterpreter
	else:
		i = Interpreter
	print """Ready. Type «help» if you don't know what to do."""
	try:
		parse(sys.stdin, interpreter=i, ctx=c)
	except Exception as e:
		fix_exception(e)
		reporter(e)
	shut_down()

from gevent import spawn,sleep
#spawn(looper)
callLater(False,0.1,ready)
mainloop()

