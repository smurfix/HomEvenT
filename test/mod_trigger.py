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
from homevent.module import load_module
from homevent.statement import main_words
from test import run

input = """\
trigger foo :sync
wait: for 1m -90s 0.5min +.5s
trigger bar :sync
trigger baz notlogged :
	log NONE
	sync
shutdown
"""

main_words.register_statement(ShutdownHandler)
load_module("trigger")
load_module("wait")

run("trigger",input)

