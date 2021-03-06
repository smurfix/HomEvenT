/*
 *  Copyright © 2008, Matthias Urlichs <matthias@urlichs.de>
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, either version 3 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License (included; see the file LICENSE)
 *  for more details.
 */

/*
 * This file defines basics for the FS20 writer.
 */

#include <stdlib.h>
#include <stdio.h>
#include <avr/io.h>
#include <avr/interrupt.h>
#include <avr/pgmspace.h>
#include "qtask.h"
#include "qdelay.h"
#include "util.h"
#include "assert.h"

#define FLOW_DATA
#include "flow_internal.h"
#include "flow.h"

#define NPULSE 5
#define WRITE_DELAY 20
#ifdef SLOW
#define OCR_INCR1 50
#define OCR_INCR2 1000
#else
#define OCR_INCR1 200
#define OCR_INCR2 5000
#endif

extern flow_head fs20_head;
extern flow_head em_head;

flow_head *flows;

enum ov {
	OV_NO, OV_YES, OV_FIRST=5, OV_RESET, OV_RESET_Q, OV_RESET_DIS, OV_RESET_DLY
	};
static enum ov overflow = OV_FIRST;
static short pulses;
static short enable_delay = 1;

static unsigned short last_icr;
static unsigned short this_icr;

static void do_times(task_head *dummy);
static task_head times_task = TASK_HEAD(do_times);

static void do_reset1(task_head *dummy);
static task_head reset1_task = TASK_HEAD(do_reset1);

static void do_reset2(task_head *dummy);
static task_head reset2_task = TASK_HEAD(do_reset2);

static void do_writer_enable(task_head *dummy);
static task_head writer_enable_task = TASK_HEAD(do_writer_enable);

static void do_reset(enum ov over);

extern void read_response(task_head *task);
void read_data(unsigned char param, unsigned char *data, unsigned char len)
{
	task_head *task = malloc(sizeof(task_head)+2+len);
	if(!task)
		report_error("out of memory");
	DBGS("read_data: type %c  len %d",param,len);
	*task = TASK_HEAD(read_response);
	unsigned char *buf = (unsigned char *)(task+1);
	*buf++ = param;
	*buf++ = len;
	while(len--)
		*buf++ = *data++;
	queue_task(task);
	enable_delay = WRITE_DELAY;
}


//static unsigned short w1t,w2t;
static void do_times(task_head *dummy)
{
	//w1t=TCNT1;
	unsigned char hi = (PINB & _BV(PB0)) ? 1 : 0;
	if(++pulses == NPULSE) {
		writer_disable();
		dequeue_task_later(&writer_enable_task);
	}
	switch(overflow)
	{
	default:
		DBGS("?? rx times exit:%d",overflow);
		return;
	case OV_NO:
	case OV_YES:
		break;
	case OV_RESET:
	case OV_FIRST:
		return;
	}

	unsigned short icr = this_icr;
#ifdef SLOW
	icr <<= 2; /* undo the shift from the sender */
#else
	icr >>= 1; /* clock is .5µs, we want µs */
#endif
	//DBGS("Time %u: %d", icr, hi);
	flow_head *fp;
	for(fp=flows;fp;fp=fp->next) {
		fp->read_time(icr,hi);
	}
	//w2t = TCNT1;
}

static void do_writer_enable(task_head *dummy)
{
	writer_enable();
}

void reader_disable()
{
	cli();
	if(overflow >= OV_RESET) {
		overflow = OV_RESET_DIS;
		sei();
		return;
	}
	do_reset(OV_RESET_DLY);
	sei();
}

void reader_enable()
{
	cli();
	if(overflow == OV_RESET_DLY)
		overflow = OV_RESET;
	else
		do_reset2(NULL);
	sei();
}

static void do_reset(enum ov over)
{
	switch(overflow)
	{
	case OV_RESET:
		DBGS("No Reset, %d",overflow);
		return;
	default:
		break;
	}
	//DBGS("Reset, %d",overflow);
	TIMSK1 &= ~(_BV(ICIE1)|_BV(OCIE1A));
	overflow = over;
	_queue_task(&reset1_task);
}
static void do_reset1(task_head *dummy)
{
	flow_head *fp;
	for(fp=flows;fp;fp=fp->next) {
		fp->read_reset();
	}


	if(overflow == OV_RESET)
		queue_task_msec(&reset2_task,20);
	else if(overflow == OV_RESET_DLY)
		overflow = OV_RESET_DIS;
	else
		do_reset2(dummy);

	if(pulses >= NPULSE)
		queue_task_msec(&writer_enable_task,enable_delay);
	pulses = 0;
	enable_delay = 1;
}
static void do_reset2(task_head *dummy)
{
	if(overflow == OV_RESET_DLY) {
		overflow = OV_RESET_DIS;
		return;
	}
	cli();
	TIFR1 |= _BV(ICF1);
	TIMSK1 |= _BV(ICIE1);
	TCCR1B |= _BV(ICES1);
	overflow = OV_FIRST;
	//DBG("reset done");
	sei();
}


ISR(TIMER1_CAPT_vect)
{
	unsigned short icr = ICR1;
	this_icr = icr-last_icr;
	TCCR1B ^= _BV(ICES1);
	switch(overflow) {
	case OV_FIRST:
		TIMSK1 |= _BV(OCIE1A);
		break;
		
	case OV_NO:
		//DBGS("Edge %u  last %u  this %u",icr, last_icr,icr);
		if(times_task.delay) {
			//DBGS("Work is too slow! %x %x  %x %x",last_icr,icr, w1t,w2t);
			do_reset(OV_RESET);
			return;
		}

		_queue_task(&times_task);
		break;

	default:
		report_error("Recv Capture ?");
		return;
	}
	OCR1A = icr + OCR_INCR1;
	TIFR1 |= _BV(OCF1A);
	TIMSK1 &= ~_BV(ICIE1);
	last_icr = icr;
	overflow = OV_YES;
}

ISR(TIMER1_COMPA_vect)
{
	if(overflow == OV_YES) {
		if(TIFR1 & _BV(ICF1)) {
			DBG("RX: Change while working");
			do_reset(OV_RESET_Q);
			return;
		}
		overflow = OV_NO;
		OCR1A = TCNT1 + (OCR_INCR2-OCR_INCR1);
		TIMSK1 |= _BV(ICIE1);
	} else {
		DBG("OCR end");
		do_reset(OV_RESET_Q);
	}
}

void rx_chain(void)
{
	static flow_head **fp = &flows;
	*fp = &fs20_head; fp = &((*fp)->next);
	*fp = &em_head; fp = &((*fp)->next);
	*fp = NULL;
}

void rx_init(void) __attribute__((naked)) __attribute__((section(".init3")));
void rx_init(void)
{
	PRR &= ~_BV(PRTIM1);
#ifdef SLOW
	TCCR1B = _BV(ICES1)|_BV(CS12)|_BV(CS11)|_BV(CS10); /* ext input */
#else
	TCCR1B = _BV(ICNC1)|_BV(ICES1)|_BV(CS11); /* 2MHz, noice cancel */
#endif
	TIMSK1 = _BV(ICIE1);
	TIFR1 = _BV(ICF1);
	TCNT1 = 0;
}

