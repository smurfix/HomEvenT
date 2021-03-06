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

from __future__ import division

"""\
This code implements a listener for environment monitoring.

"""

from homevent.module import Module
from homevent.statement import AttributedStatement,Statement, main_words
#from homevent.check import Check,register_condition,unregister_condition
from homevent.run import simple_event
#from homevent.event import Event
#from homevent.context import Context
from homevent.base import Name,SName
from homevent.fs20 import recv_handler, PREFIX
from homevent.collect import Collection,Collected
from homevent.check import register_condition,unregister_condition
from homevent.logging import log,TRACE,DEBUG
from homevent.times import now,humandelta
from homevent.timeslot import Timeslots,Timeslotted,Timeslot,collision_filter

#from twisted.internet import protocol,defer,reactor
#from twisted.protocols.basic import _PauseableMixin

PREFIX_EM = 'e'
PREFIX_EM2 = 'm'

# 
#A1A2A3V1  	T11T12T13T141  	T21T22T23T241 T31T32T33T341  	F11F12F13F141  	F21F22F23F241  	F31F32F33F341 Q1Q2Q3Q41  	S1S2S3S41
#_0..7_V 	_____0.1°____ 	_____1°______ _____10°_____ 	_____0.1%____ 	_____1%______ 	_____10%_____
#
#e01:04 060901 030705 0A03
#       +19.6°  57.3%

def em_proc_thermo_hygro(ctx, data):
	if len(data) != 7:
		simple_event(ctx, "fs20","em","bad_length","thermo_hygro",len(data),"".join("%x"%x for x in data[1:]))
		return None
	temp = data[1]/10 + data[2] + data[3]*10
	if data[0] & 8: temp = -temp
	hum = data[4]/10 + data[5] + data[6]*10
	return {"temperature":temp, "humidity":hum}
em_proc_thermo_hygro.em_name = "thermo_hygro"
em_proc_thermo_hygro.interval = 177
em_proc_thermo_hygro.interval_mod = -0.5

em_procs = [ None, # em_proc_thermo,
             em_proc_thermo_hygro,
             None, # em_proc_rain,
             None, # em_proc_wind,
             None, # em_proc_thermo_hygro_baro,
             None, # em_proc_light,
             None, # em_proc_pyrano,
             None, # em_proc_combined,
           ]

class EMs(Collection):
	name = Name("fs20","em")
EMs = EMs()
EMs.does("del")

EMcodes = {}

class EM(Collected,Timeslotted):
	storage = EMs.storage
	def __init__(self,name,group,code,ctx, faktor={},offset={}, slot=None):
		self.ctx = ctx
		self.group = group
		self.code = code
		self.offset = offset
		self.faktor = faktor
		self.last = None # timestamp
		self.last_data = None # data values
		try: g = EMcodes[group]
		except KeyError: EMcodes[group] = g = {}
		try: c = g[code]
		except KeyError: g[code] = c = []
		c.append(self)

		self._slot = slot
		if slot is not None:
			ts = Timeslot(self,name)
			p = em_procs[self.group]
			ts.interval = (p.interval + code * p.interval_mod,)
			ts.duration = slot
			ts.maybe_up()
		super(EM,self).__init__(*name)

	def get_slot(self):
		if self._slot is None:
			return None
		else:
			return Timeslots[self.name]
	slot = property(get_slot)

	def event(self,ctx,data):
		for m,n in data.iteritems():
			try: n = n * self.faktor[m]
			except KeyError: pass
			try: n = n + self.offset[m]
			except KeyError: pass

			simple_event(ctx, "fs20","em", m,n, *self.name)
		self.last = now()
		self.last_data = data

	def info(self):
		if self.last is not None:
			return "%s %d: %s" % (em_procs[self.group].em_name, self.code,
				humandelta(self.last-now()))
		else:
			return "%s %d: (never)" % (em_procs[self.group].em_name, self.code)

	def list(self):
		yield("name",self.name)
		yield("group",self.group)
		yield("groupname",em_procs[self.group].em_name)
		yield("code",self.code)
		if self.last:
			yield ("last",self.last)
		if self.last_data:
			for k,v in self.last_data.iteritems(): yield ("last_"+k,v)
		for k,v in self.faktor.iteritems(): yield ("faktor_"+k,v)
		for k,v in self.offset.iteritems(): yield ("offset_"+k,v)
		if self.slot:
			for k,v in self.slot.list(): yield ("slot_"+k,v)
	
	def delete(self,ctx=None):
		EMcodes[self.group][self.code].remove(self)
		if self._slot:
			self._slot.delete()
		super(EM,self).delete()
		if not EMcodes[self.group][self.code]: # empty array
			del EMcodes[self.group][self.code]
		

def flat(r):
	for a,b in r.iteritems():
		yield a
		yield b

class em_handler(recv_handler):
	"""Message: e0102030405"""
	def dataReceived(self, ctx, data, handler=None, timedelta=None):
		if len(data) < 4:
			return

		xsum = ord(data[-2])
		qsum = ord(data[-1])
		data = tuple(ord(d) for d in data[:-2])
		xs=0; qs=xsum
		for d in data:
			xs ^= d
			qs += d
		if xs != xsum:
			simple_event(ctx, "fs20","em","checksum1",xs,xsum,"".join("%x" % x for x in data))
			return
		if (qs+5)&15 != qsum:
			simple_event(ctx, "fs20","em","checksum2",(qs+5)&15,qsum,"".join("%x" % x for x in data))
			return
		try:
			g = em_procs[data[0]]
			if not g:
				raise IndexError(data[0])
		except IndexError:
			simple_event(ctx, "fs20","unknown","em",data[0],"".join("%x"%x for x in data[1:]))
		else:
			r = g(ctx, data[1:])
			if r is None:
				return
			try:
				hdl = EMcodes[data[0]][data[1]&7]
			except KeyError:
				simple_event(ctx, "fs20","unknown","em","unregistered",g.em_name,data[1]&7,*tuple(flat(r)))
			else:
				# If there is more than one device on the same
				# address, this code tries to find the one that's
				# most likely to be the one responsible.
				hi = [] # in slot
				hr = [] # slot not running
				hn = [] # device without slot
				for h in hdl:
					if h.slot is None:
						hn.append(h)
					elif h.slot.is_in():
						hi.append(h)
					elif not h.slot.is_out():
						hr.append(h)
				if hi:
					hi = collision_filter(r,hi)
					if len(hi) > 1:
						simple_event(ctx, "fs20","conflict","em","sync",g.em_name,data[1]&7, *tuple(flat(r)))
					else:
						hi[0].slot.do_sync()
						hi[0].event(ctx,r)
				elif hr:
					hr = collision_filter(r,hr)
					if len(hr) > 1:
						simple_event(ctx, "fs20","conflict","em","unsync",g.em_name,data[1]&7, *tuple(flat(r)))
					else:
						hr[0].slot.up(True)
						hr[0].event(ctx,r)
				elif hn:
					hn = collision_filter(r,hn)
					if len(hn) > 1:
						simple_event(ctx, "fs20","conflict","em","untimed",g.em_name,data[1]&7, *tuple(flat(r)))
					else:
						# no timeslot here
						hn[0].event(ctx,r)
				elif hdl:
					simple_event(ctx, "fs20","unknown","em","untimed",g.em_name,data[1]&7, *tuple(flat(r)))
				else:
					simple_event(ctx, "fs20","unknown","em","unregistered",g.em_name,data[1]&7, *tuple(flat(r)))

class em2_handler(em_handler):
	"""Message: m214365"""
	def dataReceived(self, ctx, data, handler=None, timedelta=None):
		if len(data) < 4:
			return
		xd = ""
		db = None
		for d in data:
			d = ord(d)
			xd += chr(d&0x0F) + chr(d>>4)

		super(em2_handler,self).dataReceived(ctx, xd, handler, timedelta)


class FS20em(AttributedStatement):
	name = "fs20 em"
	doc = "declare an FS20 EM monitor"
	long_doc = u"""\
fs20 em ‹name…›:
	code ‹type› ‹id›
	- declare an FS20 environment monitor
Known types: 
"""
	long_doc += "  "+" ".join(n.em_name for n in em_procs if n is not None)+"\n"

	group = None
	code = None
	slot = None
	def __init__(self,*a,**k):
		self.faktor={}
		self.offset={}
		super(FS20em,self).__init__(*a,**k)

	def run(self,ctx,**k):
		event = self.params(self.ctx)

		if not len(event):
			raise SyntaxError(u"‹fs20 em› needs a name")
		if self.code is None:
			raise SyntaxError(u"‹fs20 em› needs a 'code' sub-statement")
		EM(SName(event), self.group,self.code,ctx, self.faktor,self.offset, self.slot)

class FS20emScale(Statement):
	name = "scale"
	doc = "adapt values"
	long_doc=u"""\
scale ‹type› ‹factor› ‹offset›
	Adjust raw measurements for ‹type› by first multiplying by ‹factor›,
	then adding ‹offset›.
	‹type› is the same as reported in the subsequent event.
"""
	def run(self,ctx,**k):
		event = self.params(ctx)
		lo = hi = None
		if len(event) != 3:
			raise SyntaxError(u'Usage: scale ‹type› ‹factor› ‹offset›')

		name = event[0]
		if event[1] != "*":
			self.parent.factor[name] = float(event[1])
		if event[2] != "*":
			self.parent.offset[name] = float(event[2])
FS20em.register_statement(FS20emScale)

class FS20emSlot(Statement):
	name = "timeslot"
	doc = "create a time slot"
	long_doc=u"""\
timeslot [‹seconds›]
	Create a timeslot with the same name as this device.
	Only measurements arriving in that timeslot will be considered.
	You can simply stop the timeslot if you need to re-sync.
	The optional seconds parameter is the duration of the slot;
	it defaults to one second.
"""
	def run(self,ctx,**k):
		event = self.params(ctx)
		if len(event) > 1:
			raise SyntaxError(u'Usage: timeslot [‹seconds›]')
		if len(event):
			sec = float(event[0])
		else:
			sec = 1
		self.parent.slot = sec
FS20em.register_statement(FS20emSlot)

class FS20emcode(Statement):
	name = "code"
	doc = "declare the code type and number for an EM device"
	long_doc = u"""\
code ‹type› ‹id›
	- declare the type and ID of an EM device
Known types:
"""
	long_doc += "  "+" ".join(n.em_name for n in em_procs if n is not None)+"\n"

	def run(self,ctx,**k):
		event = self.params(self.ctx)
		if len(event) != 2:
			raise SyntaxError(u"Usage: ‹fs20 em› ‹name…›: ‹code› ‹type› ‹id›")
		id = 0
		for p in em_procs:
			if p is not None and p.em_name == event[0]:
				self.parent.group = id
				try:
					id = int(event[1])
				except (TypeError,ValueError):
					raise SyntaxError(u"‹fs20 em› ‹name…›: ‹code›: ID must be a number")
				else:
					if id<0 or id>7:
						raise SyntaxError(u"‹fs20 em› ‹name…›: ‹code›: ID between 0 and 7 please")
					self.parent.code = id
				return
			id += 1
		raise SyntaxError(u"Usage: ‹fs20 em› ‹name…›: ‹code›: Unknown type")
FS20em.register_statement(FS20emcode)


class FS20emVal(Statement):
	name = "set fs20 em"
	doc = "Set the last-reported value for a device"
	long_doc = u"""\
set fs20 em ‹type› ‹value› ‹name…›
	- Set a last-reported value. This is used to distinguish devices
	  which are set to the same ID after start-up.
"""

	def run(self,ctx,**k):
		event = self.params(self.ctx)
		if len(event) < 3:
			raise SyntaxError(u"Usage: set fs20 em ‹type› ‹value› ‹name…›")
		d = EMs[Name(*event[2:])]
		if d.last_data is None: d.last_data = {}
		d.last_data[event[0]] = float(event[1])


class fs20em(Module):
	"""\
		Basic fs20 EM reception.
		"""

	info = "Basic fs20 environment monitor"

	def load(self):
		PREFIX[PREFIX_EM] = em_handler()
		PREFIX[PREFIX_EM2] = em2_handler()
		main_words.register_statement(FS20em)
		main_words.register_statement(FS20emVal)
		register_condition(EMs.exists)
	
	def unload(self):
		del PREFIX[PREFIX_EM]
		del PREFIX[PREFIX_EM2]
		main_words.unregister_statement(FS20em)
		main_words.unregister_statement(FS20emVal)
		unregister_condition(EMs.exists)
	
init = fs20em
