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

from homevent.reactor import ShutdownHandler
from homevent.module import load_module,Load
from homevent.statement import DoNothingHandler,main_words
from homevent.check import register_condition
from test import run

input = """\
if not exists module bool: load bool
if not exists module ifelse: load ifelse
if not exists module logging: load logging
if not exists module block: load block
if not exists module trigger: load trigger
if not exists module wait: load wait
if not exists module onewire: load onewire
if not exists module on_event: load on_event
if not exists module errors: load errors
if not exists module monitor: load monitor
#

monitor onewire "10.000010ef0000" temperature:
	name tempi
	require 2 0.1
	delay for 3
	stopped

on onewire up * "10.000010ef0000":
	name light sensor present
	start monitor tempi

on onewire scanned A * * *:
	name scanned

	del on scanned

	input onewire "10.000010ef0000" temperature :name temp
	var input X temp
	trigger thermo $X
	list input temp

	output onewire "10.000010ef0000" temp_high :name temphi
	set output 99 temphi

	del wait yawn

connect onewire A localhost 54300
#
block:
	try:
		wait yawn:
			for 10
			debug force
		shutdown
	catch:
		do nothing

log TRACE DirStart
dir onewire A
log TRACE DirDev
dir onewire "10.000010ef0000"
block:
	if exists onewire device "10.000010ef0000":
		log TRACE yes
	else:
		log TRACE no
log TRACE DirStop
#set onewire 30 "10.000010ef0000" templow ## not when testing
scan onewire A
dir onewire "10.000010ef0000"
dir onewire A
list onewire device
list onewire device "10.000010ef0000"
wait before disconnect:
	for 0.3
	debug force
disconnect onewire A
wait END:
	for 1
	debug force
shutdown
"""

main_words.register_statement(DoNothingHandler)
main_words.register_statement(ShutdownHandler)
main_words.register_statement(Load)

load_module("block")
load_module("file")
load_module("ifelse")
load_module("path")
load_module("data")

run("onewire",input)

