# -*- coding: utf-8 -*-

##
##  Copyright © 2008-2012, Matthias Urlichs <matthias@urlichs.de>
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

from __future__ import division

"""\
This code contains the framework for timing regular events.

"""

from homevent.statement import AttributedStatement, Statement
from homevent.event import Event
from homevent.run import process_event,process_failure
from homevent.reactor import shutdown_event
from homevent.times import time_delta, time_until, unixdelta, now, \
	humandelta
from homevent.base import Name
from homevent.twist import callLater, fix_exception
from homevent.context import Context
from homevent.check import register_condition
from homevent.logging import log,TRACE,DEBUG,ERROR
from homevent.collect import Collection,Collected

from time import time
import os
import datetime as dt

class Timeslots(Collection):
    name = "timeslot"
Timeslots = Timeslots()
Timeslots.does("del")
register_condition(Timeslots.exists)

class Timeslotted(object):
	pass
#	def slot_up(self):
#		pass
#	def slot_down(self):
#		pass

class TimeslotError(RuntimeError):
    def __init__(self,w):
        self.timeslot = w
    def __str__(self):
        return self.text % (" ".join(str(x) for x in self.timeslot.name),)
    def __unicode__(self):
        return self.text % (" ".join(unicode(x) for x in self.timeslot.name),)

class AlreadyRunningError(TimeslotError):
    text = u"A The timer ‹%s› is already active"


class Timeslot(Collected):
	"""This is the thing that watches."""
	storage = Timeslots.storage

	last = None # last time I was called
	next = None # next time I should be called
	running = "off" # state
		# off: not running
		# next: wait for next event, not in slot
		# pre: wait for event trigger, in slot
		# during: event in progress, in slot (obviously)
		# post: after event, in slot
		# error: timer is dead / out of sync
	waiter = None # trigger for next event
	slotter = None # trigger for time slot
	shift = 0.5 # position during the slot when the event will trigger

	duration = 1 # length of slot
	interval = None # time between slots; set externally

	def __init__(self,parent,name):
		self.ctx = parent.ctx
		self.parent = parent
		super(Timeslot,self).__init__(*name)

	def __repr__(self):
		return u"‹%s %s %s›" % (self.__class__.__name__, self.running)

	def list(self):
		yield ("name"," ".join(unicode(x) for x in self.name))
		yield ("run",self.running)
		if self.interval is not None:
			yield ("interval"," ".join(str(x) for x in self.interval))
		yield ("duration",self.duration)
		if self.last is not None:
			yield ("last",self.last)
		if self.next is not None:
			yield ("next",self.next)
		if self.slotter is not None:
			yield ("slot",(unixdelta(self.next-now()))/self.duration)

	def info(self):
		if self.running not in ("off","error"):
			tm = unixdelta(self.next-now())
		elif self.last is not None:
			tm = unixdelta(now()-self.last)
		else:
			tm = "never"
		return "%s %s" % (self.running,tm)

	def do_pre(self):
		self.waiter = None
		if self.running != "next" or self.slotter is not None:
			log(ERROR,"timeslot error pre",self.running,*self.name)
			return

		self.running = "pre"
		if self.next is None:
			self.next = now()
		self.last = self.next

		try:
			process_event(Event(self.ctx,"timeslot","begin",*self.name))
			if self.running == "pre":
				self.running = "during"
				self.next += dt.timedelta(0,self.duration)
				self.slotter = callLater(False,self.next, self.do_post)
			elif self.running not in ("off","error"):
				log(ERROR,"timeslot error pre2",self.running,*self.name)
			else:
				self.next = None
		except Exception as e:
			fix_exception(e)
			self.dead(e)
	
	def do_sync(self):
		self.down()
		self.running = "during"
		self.next = now()+dt.timedelta(0,self.duration/2)
		self.slotter = callLater(False,self.next, self.do_post)
	
	def do_post(self):
		self.slotter = None
		if self.running != "during" or self.waiter is not None:
			log(ERROR,"timeslot error post",self.running,*self.name)
			return

		self.running = "post"
		try:
			process_event(Event(self.ctx,"timeslot","end",*self.name))
			if self.running == "post":
				self.running = "next"
				self.next = time_delta(self.interval, now=self.next)-dt.timedelta(0,self.duration)
				self.waiter = callLater(False, self.next, self.do_pre)
			elif self.running not in("off","error"):
				log(ERROR,"timeslot error post2",self.running,*self.name)
		except Exception as e:
			fix_exception(e)
			self.dead(e)


	def dead(self,_):
		self.running = "error"
		process_failure(_)
		self.down()
		simple_event(self.ctx,"timeslot","error",*self.name)


	def delete(self,ctx=None):
		self.down()
		super(Timeslot,self).delete()
		return


	def is_up(self):
		return self.running not in ("off","error")
	def is_in(self):
		return self.running in ("pre","during","post")
	def is_out(self):
		return self.running == "next"
		
	def up(self, resync=False):
		if self.running not in ("off","error"):
			if not resync:
				raise AlreadyRunningError(self)
		if resync:
			self.do_sync()
		else:
			self.running = "next"
			self.next = time_delta(self.interval, now=self.last)
			self.waiter = callLater(False, self.next, self.do_pre)
#			self.parent.slot_up()
		
	def maybe_up(self, resync = False):
		if self.running not in ("off","error"):
			return
		if self.last is not None:
			self.running = "next"
			self.next = time_delta(self.interval, now=self.last)
			self.waiter = callLater(False, self.next, self.do_pre)

	def down(self):
		if self.waiter:
			self.waiter.cancel()
			self.waiter = None
		if self.slotter:
			self.slotter.cancel()
			self.slotter = None
#		self.parent.slot_down()
		self.running = "off"
		self.next = None


class SomeNull(Exception): pass

def collision_filter(val, hdl):
	"""\
		Try to find the device that's closest to the last-reported values.
		This only works when all devices have some common previous
		measurement.
		‹val› is the reported type/value hash, ‹hdl› a list of devices.
		"""
	if len(hdl) < 2:
		return hdl
	for h in hdl:
		if h.last_data is None:
			return hdl
	dm = []
	for k in val.iterkeys():
		try:
			for h in hdl:
				if k not in h.last_data:
					raise SomeNull
			dm.append(k)
		except SomeNull: pass
	if not dm:
		return hdl

	d = None
	f = None
	for h in hdl:
		dn = 0
		for k in dm:
			dn += abs(h.last_data[k] - val[k])

		if d is None or dn < d*2/3:
			d = dn
			f = h
		elif dn < d*3/2: # not enough separation
			if d < dn: d = dn
			f = None
	if f is None:
		return hdl
	return (f,)
	
