# -*- coding: utf-8 -*-

"""\
This code does basic event mongering.

trigger FOO...
	- sends the FOO... event

"""

from homevent.statement import Statement, main_words
from homevent.event import Event
from homevent.run import process_event, process_failure


class TriggerHandler(Statement):
	name=("trigger",)
	doc="send an event"
	long_doc="""\
trigger FOO...
	- creates a FOO... event. Errors handling the event are reported
	  asynchronously.
"""
	def run(self,ctx,**k):
		event = self.params(ctx)
		if not event:
			raise SyntaxError("Events need at least one parameter")
		process_event(Event(self.ctx,*event)).addErrback(process_failure)

class SyncTriggerHandler(TriggerHandler):
	name=("sync","trigger")
	doc="send an event and wait for it"
	long_doc="""\
sync trigger FOO...
	- creates a FOO... event and wait until it is processed. Errors
	  handling the event are propagated to the caller.
"""
	def run(self,ctx,**k):
		event = self.params(ctx)
		if not event:
			raise SyntaxError("Events need at least one parameter")
		return process_event(Event(self.ctx,*event))


from homevent.module import Module

class TriggerModule(Module):
	"""\
		This module contains basic event handling code.
		"""

	info = "Basic event handling"

	def load(self):
		main_words.register_statement(TriggerHandler)
		main_words.register_statement(SyncTriggerHandler)
	
	def unload(self):
		main_words.unregister_statement(TriggerHandler)
		main_words.unregister_statement(SyncTriggerHandler)

init = TriggerModule
