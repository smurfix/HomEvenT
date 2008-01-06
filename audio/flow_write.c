/*
 *  Copyright © 2007, Matthias Urlichs <matthias@urlichs.de>
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

#include <stdio.h>
#include <malloc.h>
#include <string.h>
#include <errno.h>
#include "flow_internal.h"

/* Note that care must be taken to keep accurate track of how many bytes
 * per second need to get sent, given that the time a byte requires
 * processing for cannot be represented accurately.
 *
 * Not if you have a sample rate of 44100 bytes/sec, anyway.
 *
 * This code assumes, however, that the sample rate itself
 * *can* be thus represented.
 */

void
flow_setup_writer(FLOW_PARAM
                  unsigned int nsync, unsigned int param[W_IDLE])
{
	unsigned int i;
	F_w_sync = nsync;
	for(i=W_IDLE+1; i-- > 0;) {
		F_w_times[i] = flow_rate(f,param[i]);
	}
}

void
flow_writer(FLOW_PARAM
            flow_writeproc proc, void *param)
{
	F_writer = proc;
	F_writer_param = param;
}

int
flow_write_buf(FLOW_PARAM
               unsigned char *data, unsigned int len)
{
	unsigned char par;

	/* One high/low sequence */
	inline void R(int _x)
	{
		F_writer(F_writer_param, F_w_times[_x+W_MARK],F_w_times[_x+W_SPACE]);
	}
	inline void X(unsigned char _y) /* one bit */
	{
		if(_y) {
			R(W_ONE);
			par ^= 1;
		} else
			R(W_ZERO);
	}

	inline void Xpar()
	{
		switch(F_parity) {
		case P_NONE: break;
		case P_MARK: X(1); break;
		case P_SPACE: X(0); break;
		case P_ODD: X(par ^ 1); break;
		case P_EVEN: X(par); break;
		}
	}

	inline void BM(unsigned char _b) /* one byte plus parity, MSB first */ 
	{
		unsigned char _m = 1<<(F_bits-1);

		par=0;
		while(_m) {
			X(_b & _m);
			_m >>= 1;
		}
		Xpar();
	}

	inline void BL(unsigned char _b) /* one byte plus parity, LSB first */ 
	{
		unsigned char par=0;
		unsigned char _m = F_bits;
		while(_m--) {
			X(_b & 1);
			_b >>= 1;
		}
		Xpar(); /* parity */
	}

	unsigned int i;

	/* sync sequence */
	for(i=0;i<F_w_sync;i++)
		R(0);
	R(1);

	if(F_msb)
		while(len--) BM(*data++);
	else
		while(len--) BL(*data++);
	R(0); /* one last bit, to mark the end */
	     /* this is because the decoder may just look at the pause lengths */

	F_writer(F_writer_param, 0,F_w_times[W_IDLE]);
	return 0;
}

