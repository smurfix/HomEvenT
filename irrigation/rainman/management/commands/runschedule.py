# -*- coding: utf-8 -*-

##
##  Copyright © 2012, Matthias Urlichs <matthias@urlichs.de>
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
		Run the current schedule, watch out for rain
		"""

from __future__ import division,absolute_import
from homevent import gevent_rpyc
gevent_rpyc.patch_all()

from traceback import format_exc,print_exc
import sys
import gevent,rpyc
from gevent.queue import Queue
from rpyc.core.service import VoidService
from optparse import make_option

from django.core.management.base import BaseCommand, CommandError
from rainman.models import Site,Valve,Schedule,Controller,History
from rainman.utils import now
from rainman.logging import log,log_error
from datetime import datetime,time,timedelta
from django.db.models import F,Q

class Command(BaseCommand):
	args = ''
	help = 'Run the current schedule, watch for rain, etc.'

	option_list = BaseCommand.option_list + (
		make_option('-s','--site',
			action='store',
			dest='site',
			default=None,
			help='Limit to this Site (all controllers)'),
		make_option('-c','--controller',
			action='store',
			dest='controller',
			default=None,
			help='Controller to generate a config file snippet for'),
		make_option('-t','--timeout',
			action='store',type='int',
			dest='timeout',
			default=600,
			help='Run main processing loop every N seconds'),
		)

	def handle(self, *args, **options):
		q = Q()
		if options['site']:
			q &= Q(site__name=options['site'])
		if options['controller']:
			q &= Q(name=options['controller'])
		for c in Controller.objects.filter(q):
			s = SchedSite(c.site)
			s.run_every(options['timeout'])
			SchedController(c)

		if not controllers:
			raise RuntimeError("No matching controllers found.")
		while True:
			gevent.sleep(99999)



class RestartService(VoidService):
	def on_disconnect(self,*a,**k):
		for s in sites.itervalues():
			s.maybe_restart(self)

class Meter(object):
	sum_it = False
	@property
	def weight(self):
		return self.d.weight
	def __init__(self,dev):
		self.d = dev
		self.site = SchedSite(dev.site)
		self.reconnect()

	def callback(self,event=None,**k):
		"""monitor value NUMBER name…"""
		try:
			print >>sys.stderr,self.__class__.__name__,self.d.name,event
			val = float(event[2])
			self.add_value(val)
		except Exception:
			print_exc()

	def reconnect(self):
		if not self.d.var:
			return
		print >>sys.stderr," ".join(("Connect to","monitor","value","*")+tuple(self.d.var.split()))
		self.mon = self.site.ci.root.monitor(self.callback,"monitor","value","*",*(self.d.var.split()))

	def log(self,txt):
		self.site.log(("%s %s: "%(self.meter_type,self.d.name))+txt)

class SumMeter(Meter):
	sumval = 0
	def get_value(self):
		r,self.sumval = self.sumval,0
		return r
		
	def add_value(self,val):
		self.sumval += val

class RainMeter(SumMeter):
	meter_type="rain"

	def add_value(self,val):
		super(RainMeter,self).add_value(val)
		if val > 0:
			self.site.has_rain()

class FeedMeter(SumMeter):
	meter_type="feed"
	sum_it = True
	weight = 1
	def __init__(self,*a,**k):
		super(FeedMeter,self).__init__(*a,**k)
		self.valves = set()
		for f in self.d.valves.all():
			self.valves.add(SchedValve(f))

class AvgMeter(Meter):
	val = None
	avg = 0
	nval = 0
	ts = None

	def reconnect(self):
		super(AvgMeter,self).reconnect()
		self.ts = None

	def get_value(self):
		if self.ts is None:
			return None
		self.snapshot()
		if not self.nval:
			return None
		r = self.avg / self.nval
		self.avg = 0
		self.nval = 0
		return r

	def snapshot(self):
		n = now()
		if self.ts is not None and self.val is not None:
			w=(n-self.ts).total_seconds()
			if w > 300: w = 300 # if the measurer dies
			self.avg += w*self.val
			self.nval += w
		self.ts = n
	
	def add_value(self,val):
		self.snapshot()
		self.val = val

class TempMeter(AvgMeter):
	meter_type="temp"

class WindMeter(AvgMeter):
	meter_type="wind"

class SunMeter(AvgMeter):
	meter_type="sun"

METERS=[]
for m in globals().values():
	if hasattr(m,"meter_type"):
		METERS.append(m)


class SchedCommon(object):
	def log(self,txt):
		raise NotImplementedError("You forgot to implement %s.log" % (self.__class__.__name__,))
	def log_error(self,context=None):
		self.log(format_exc()+repr(context))

sites = {}
controllers = {}
paramgroups = {}
valves = {}

class ParamGroup(SchedCommon):
	"""Mirrors a parameter group for valves"""
	def __new__(cls,pargroup):
		if pargroup.id in paramgroups:
			return paramgroups[pargroup.id]
		self = object.__new__(cls)
		paramgroups[pargroup.id] = self
		self.pg = pargroup
		self.log("Startup")
		return self
	def __init__(self,site):
		pass

	def log(self,txt):
		log(self.pg.site,"ParamGroup "+self.pg.name+": "+txt)

	def env_factor_one(self, temp,wind,sun):
		p=4 # power factor, favoring nearest-neighbor

		q=Q()
		q &= Q(temp__isnull=(temp is None))
		q &= Q(wind__isnull=(wind is None))
		q &= Q(sun__isnull=(sun is None))

		sum_f = 0
		sum_w = 0
		for ef in self.pg.environment_effects.filter(q):
			d=0
			if temp is not None:
				d += (temp-ef.temp)**2
			if wind is not None:
				d += (wind-ef.wind)**2
			if sun is not None:
				d += (sun-ef.sun)**2
			d = d**(p*0.5)
			if d < 0.001: # close enough
				return ef.factor
			sum_f += ef.factor/d
			sum_w += 1/d
		if sum_w:
			sum_f /= sum_w
		return sum_f


	def env_factor(self,e):
		"""Calculate a weighted factor based on the given environmental parameters"""
		# These weighing 
		ql=(
			(10,e.temp,e.wind,e.sun),
			(4,None  ,e.wind,e.sun),
			(4,e.temp,None  ,e.sun),
			(4,e.temp,e.wind,None ),
			(1,e.temp,None  ,None ),
			(1,None  ,e.wind,None ),
			(1,None  ,None  ,e.sun),
			)
		sum_f = 0
		sum_w = 0
		for weight,temp,wind,sun in ql:
			f = self.env_factor_one(temp,wind,sun)
			if f is not None:
				sum_f += f*weight
				sum_w += weight
		if sum_w:
			sum_f /= sum_w
		return sum_f

class SchedSite(SchedCommon):
	"""Mirrors a site"""
	rain_timer = None
	rain_counter = 0
	_run_delay = None

	def __new__(cls,site):
		if site.id in sites:
			return sites[site.id]
		self = object.__new__(cls)
		sites[site.id] = self
		self.s = site
		self.connect()

		self.controllers = set()
		self.meters = {}
		for M in METERS:
			ml = set()
			self.meters[M.meter_type] = ml
			for d in getattr(self.s,M.meter_type+"_meters",()).all():
				ml.add(M(d))

		log(self.s,"Startup")
		return self
	def __init__(self,site):
		pass

	def connect(self):
		self.ci = rpyc.connect(host=self.s.host, port=int(self.s.port), ipv6=True, service=RestartService)

	def maybe_restart(self):
		try:
			self.connect()
		except Exception:
			print_exc()
			gevent.sched_later(100,self.maybe_restart())
		else:
			self.reconnect()

	def reconnect(self):
		for c in self.controllers:
			c.reconnect()
		for mm in self.meters.itervalues():
			for m in mm:
				m.reconnect()

	def log(self,txt):
		log(self.s,txt)

	def add_controller(self,controller):
		self.controllers.add(controller)

	def no_rain(self):
		"""Rain has stopped."""
		# called by timer
		self.log("Stopped raining")
		self.rain_timer = None
		rain = 0
		for rw in self.rainwatchers:
			r = rw.get_rain()
			if rain < r: rain = r
		run_calc(self,rain=rain)

	def has_rain(self):
		"""Some monitor told us that it started raining"""
		if self.rain_timer:
			self.rain_timer.kill()
		else:
			self.log("Started raining")
		self.rain = True

		n=now()
		for v in self.c.valves.all():
			if v.runoff == 0:
				continue # not affected by rain
			try:
				self.ci.command("set","output","off",*(v.location.split()))
			except Exception:
				self.log_error(v)
			v.schedules.filter(start__gte=n).delete()
			for sc in v.schedules.filter(start__gte=now()-timedelta(1),seen=True):
				if sc.start+sc.duration > n:
					sc.duration=n-sc.start
					sc.save()
		self.run_calc()
				
		self.rain_timer = gevent.spawn_later(300,self.no_rain)

	def run_every(self,delay):
		"""Initiate running the calculation and scheduling loop every @delay seconds."""

		if self._run_delay is not None:
			self._run_delay = delay # just update
			return
		self._run_delay = delay
		self._run_last = now()
		self._run = gevent.spawn_later(self._run_delay, self.run_calc, kill=False)
		self._running = False
		self._running_rain = 0

	def run_calc(self, kill=True, rain=0):
		"""Run the calculation loop."""
		if self._running:
			self._running_rain += rain
			return
		self._running = True
		try:
			if kill:
				self._run.kill()
			ts = (now()-self._run_last).total_seconds()
			if ts < 10:
				self._run = gevent.spawn_later(10-ts, self.run_calc, kill=False, rain=rain)
				return
			rain += self._running_rain
			self._running_rain = 0
			self.calc_history(rain=rain)
			self._run = gevent.spawn_later(self._run_delay, self.run_calc, kill=False)
		finally:
			self._running = False

	def calc_history(self,rain=0,kill=True):
		"""Create a new history entry"""
		values = {}
		for t,ml in self.meters.items():
			if t == "rain":
				sum_val = 10*rain
				sum_f = 10
			else:
				sum_val = 0
				sum_f = 0
			sum_it = False
			for m in ml:
				f = m.weight
				v = m.get_value()
				if v is not None:
					sum_val += f*v
					sum_f += f
				if m.sum_it: sum_it = True
			if sum_f:
				if not sum_it:
					sum_val /= sum_f
				values[t] = sum_val
		
		print >>sys.stderr,"Values:",values
		h = History(site=self.s,time=now(),**values)
		h.save()
		return

	def main_task(self):
		self.run_calc()


class SchedController(SchedCommon):
	"""Mirrors a controller"""

	def __new__(cls,c):
		if c.id in controllers:
			return controllers[c.id]
		self = object.__new__(cls)
		controllers[c.id] = self
		self.c = c
		self.site = SchedSite(self.c.site)
		self.site.add_controller(self)

	def __init__(self,c):
		pass
	
	def log(self,txt):
		log(self.c,txt)

class SchedValve(SchedCommon):
	"""Mirrors a valve."""
	def __new__(cls,valve):
		if valve.id in valves:
			return valves[valve.id]
		self = object.__new__(cls)
		valves[valve.id] = self
		self.v = valve
		self.site = SchedSite(self.v.controller.site)
		self.params = ParamGroup(self.v.param_group)
		self.reconnect()
		return self
	def __init__(self,site):
		pass
	def reconnect(self):
		print >>sys.stderr," ".join(("Connect to","output","set","*","*")+tuple(self.v.var.split()))
		self.mon = self.site.ci.root.monitor(self.callback,"output","set","*","*",*(self.v.var.split()))
		
	def callback(self,event=None,**k):
		"""output set OLD NEW NAME"""
		try:
			print >>sys.stderr,self.__class__.__name__,self.v.name,event
		except Exception:
			print_exc()

	def log(self,txt):
		log(self.v,txt)
	