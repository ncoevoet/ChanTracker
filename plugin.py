###
# Copyright (c) 2013, nicolas coevoet
# Copyright (c) 2010, Daniel Folkinshteyn - taken some ideas about threading database ( MessageParser )
# Copyright (c) 2004, Jeremiah Fincher - taken duration parser from plugin Time
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

###

import os
import time
import supybot.utils as utils
from supybot.commands import *
import supybot.commands as commands
import supybot.plugins as plugins
import supybot.ircutils as ircutils
import supybot.ircmsgs as ircmsgs
import supybot.callbacks as callbacks
import supybot.ircdb as ircdb
import supybot.log as log
import supybot.schedule as schedule
from string import Template
from sets import Set
import socket
import re
import sqlite3

def isIp(s):
	# return true if string is a valid ip address
	if is_valid_ipv4_address(s) or is_valid_ipv6_address(s):
		return True
	return False

def is_valid_ipv4_address(address):
	# return true if string is a valid ipv4 address
	try:
		socket.inet_pton(socket.AF_INET, address)
	except AttributeError:
		try:
			socket.inet_aton(address)
		except socket.error:
			return False
		return address.count('.') == 3
	except socket.error:  
		return False

	return True

def is_valid_ipv6_address(address):
	# return true if string is a valid ipv6 address
	try:
		socket.inet_pton(socket.AF_INET6, address)
	except socket.error:  
		return False
	return True

def matchHostmask (pattern,n):
	# return the machted pattern for pattern, for Nick
	if n.prefix == None or not ircutils.isUserHostmask(n.prefix):
		return None
	(nick,ident,host) = ircutils.splitHostmask(n.prefix)
	# TODO needs to implement CIDR masks
	if host.find('/') != -1:
		# cloaks
		if n.ip == None and host.startswith('gateway/web/freenode/ip.'):
			n.setIp(host.split('ip.')[1])
	else:
		# trying to get ip
		if n.ip == None and not isIp(host):
			try:
				r = socket.getaddrinfo(host,None)
				if r != None:
					u = {}
					L = []
					for item in r:
						if not item[4][0] in u:
							u[item[4][0]] = item[4][0]
							L.append(item[4][0])
					if len(L) == 1:
						# when more than one ip is returned for the domain,
						# don't use ip, otherwise it could not match
						n.setIp(L[0])
			except:
				n.setIp(None)
		if isIp(host):
			n.setIp(host)
	if n.ip != None and ircutils.hostmaskPatternEqual(pattern,'%s!%s@%s' % (nick,ident,n.ip)):
		return '%s!%s@%s' % (nick,ident,n.ip)
	if ircutils.hostmaskPatternEqual(pattern,n.prefix):
		return n.prefix
	return None
	
def matchAccount (pattern,pat,negate,n):
	# for $a, $~a, $a: extended pattern
	if negate:
		if not len(pat) and n.account == None:
			return n.prefix
	else:
		if len(pat):
			if n.account != None and ircutils.hostmaskPatternEqual('*!*@%s' % pat, '*!*@%s' % n.account):
				return '$a:'+n.account
		else:
			if n.account != None:
				return '$a:'+n.account
	return None

def matchRealname (pattern,pat,negate,n):
	# for $~r $r: extended pattern
	if n.realname == None:
		return None
	if negate:
		if len(pat):
			if not ircutils.hostmaskPatternEqual('*!*@%s' % pat, '*!*@%s' % n.realname):
				return '$r:'+n.realname
	else:
		if len(pat):
			if ircutils.hostmaskPatternEqual('*!*@%s' % pat, '*!*@%s' % n.realname):
				return '$r:'+n.realname
	return None

def matchGecos (pattern,pat,negate,n):
	# for $~x, $x: extended pattern
	if n.realname == None:
		return None
	tests = []
	(nick,ident,host) = ircutils.splitHostmask(n.prefix)
	tests.append(n.prefix)
	if n.ip != None:
		tests.append('%s!%s@%s' % (nick,ident,n.ip))
	for test in tests:
		test = '%s#%s' % (test,n.realname)
		if negate:
			if not ircutils.hostmaskPatternEqual(pat,test):
				return test
		else:
			if ircutils.hostmaskPatternEqual(pat,test):
				return test
	return None

def match (pattern,n):
	# check if given pattern match an Nick
	if pattern.startswith('$'):
		p = pattern[1:]
		negate = p[0] == '~'
		if negate:
			p = p[1:]
		t = p[0]
		p = p[1:]
		if len(p):
			# remove ':'
			p = p[1:]
		if t == 'a':
			return matchAccount (pattern,p,negate,n)
		elif t == 'r':
			return matchRealname (pattern,p,negate,n)
		elif t == 'x':
			return matchGecos (pattern,p,negate,n)
		else:
			log.error('%s unknown pattern' % pattern)
	else:
		if ircutils.isUserHostmask(pattern):
			return matchHostmask(pattern,n)
		else:
			if pattern.find('$'):
				# channel forwards
				pattern = pattern.split('$')[0]
				if ircutils.isUserHostmask(pattern):
					return matchHostmask(pattern,n)
				else:
					log.error('%s unknown pattern' % pattern)
			else:
				log.error('%s unknown pattern' % pattern)
	return None

def getBestPattern (n):
	# return best pattern for a given Nick
	results = []
	if not n.prefix or not ircutils.isUserHostmask(n.prefix):
		return []
	(nick,ident,host) = ircutils.splitHostmask(n.prefix)
	if ident.startswith('~'):
		ident = '*'
	else:
		if host.startswith('gateway/web/freenode/ip.') or host.startswith('gateway/tor-sasl/') or host.startswith('unaffiliated/'):
			ident = '*'
	if n.ip != None:
		if n.ip.find('::') > 4:
			# large ipv6
			a = n.ip.split(':')
			m = a[0]+':'+a[1]+':'+a[2]+':'+a[3]+':*'
			results.append('*!%s@%s' % (ident,m))
		else:
			results.append('*!%s@%s' % (ident,n.ip))
	if host.find('/') != -1:
		# cloaks
		if host.startswith('gateway/'):
			h = host.split('/')
			# gateway/type/(domain|account) [?/random]
			p = ''
			if len(h) > 3:
				p = '/*'
				h = h[:3]
				host = '%s%s' % ('/'.join(h),p)		
		elif host.startswith('nat/'):
			h = host.replace('nat/','')
			if h.find('/') != -1:
				host = 'nat/%s/*' % h.split('/')[0]
		if not ircutils.userFromHostmask(n.prefix).startswith('~') and not host.startswith('unaffiliated/'):
			ident = ircutils.userFromHostmask(n.prefix)
		if host.find('gateway/') != -1 and host.find('/x-') != -1:
			host = '%s/*' % host.split('/x-')[0]
	results.append('*!%s@%s' % (ident,host))
	if n.account:
		results.append('$a:%s' % n.account)
	if n.realname:
		results.append('$r:%s' % n.realname.replace(' ','?'))
	return results

def clearExtendedBanPattern (pattern):
	# a little method to cleanup extended pattern
	if pattern.startswith('$'):
		pattern = pattern[1:]
		if pattern.startswith('~'):
			pattern = pattern[1:]
		pattern = pattern[1:]
		if pattern.startswith(':'):
			pattern = pattern[1:]
	return pattern

def floatToGMT (t):
	f = None
	try:
		f = float(t)
	except:
		return None
	return time.strftime('%Y-%m-%d %H:%M:%S GMT',time.gmtime(f))

class SpamQueue(object):
	timeout = 0
	def __init__(self, timeout=None, queues=None):
		if timeout is not None:
			self.timeout = timeout
		if queues is None:
			queues = ircutils.IrcDict()
		self.queues = queues

	def __repr__(self):
		return 'SpamQueue(timeout=%r,queues=%s)' % (self.timeout,repr(self.queues))

	def reset (self,data):
		q = self._getQueue(data,insert=False)
		if q is not None:
			q.reset()
			key = self.key(data)
			self.queues[key] = q

	def key (self,data):
		return data[0]

	def getTimeout(self):
		if callable(self.timeout):
			return self.timeout()
		else:
			return self.timeout

	def _getQueue(self,data,insert=True):
		try:
			return self.queues[self.key(data)]
		except KeyError:
			if insert:
				getTimeout = lambda : self.getTimeout()
				q = utils.structures.TimeoutQueue(getTimeout)
				self.queues[self.key(data)] = q
				return q
			else:
				return None

	def enqueue(self,data,what=None):
		if what is None:
			what = data
		q = self._getQueue(data)
		q.enqueue(what)

	def len (self,data):
		q = self._getQueue(data,insert=False)
		if q is not None:
			return len(q)
		else:
			return 0

	def has (self,data,what):
		q = self._getQueue(data,insert=False)
		if q is not None:
			if what is None:
				what = data
			for elt in q:
				if elt == what:
					return True
		return False

class Ircd (object):
	# define an ircd, keeps Chan and Nick items
	def __init__(self,irc,logsSize):
		object.__init__(self)
		self.irc = irc
		self.name = irc.network
		self.channels = {}
		self.nicks = {}
		self.caps = {}
		# contains IrcMsg
		self.queue = utils.structures.smallqueue()
		self.logsSize = logsSize
	
	def getItem (self,irc,uid):
		# return active item
		if not irc or not uid:
			return None
		for channel in self.channels.keys():
			chan = self.getChan(irc,channel)
			items = chan.getItems()
			for type in items.keys():
				for value in items[type]:
					item = items[type][value]
					if item.uid == uid:
						return item	
		return None
	
	def info (self,irc,uid,prefix,db):
		# return mode changes summary
		if not uid or not prefix:
			return []
		c = db.cursor()
		c.execute("""SELECT channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE id=?""",(uid,))
		L = c.fetchall()
		if not len(L):
			c.close()
			return []
		(channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by) = L[0]
		if not ircdb.checkCapability(prefix, '%s,op' % channel):
			if prefix != irc.prefix:
				c.close()
				return []
		results = []
		current = time.time()
		results.append('[%s][%s], %s sets +%s %s' % (channel,floatToGMT(begin_at),oper,kind,mask))
		if not removed_at:
			if begin_at == end_at:
				results.append('setted forever')
			else:
				results.append('setted for %s' % utils.timeElapsed(end_at-begin_at))
				results.append('with %s more' % utils.timeElapsed(end_at-current))
				results.append('ends at [%s]' % floatToGMT(end_at))
		else:
			results.append('was active %s and ended on [%s]' % (utils.timeElapsed(removed_at-begin_at),floatToGMT(removed_at)))
			results.append('was setted for %s' % utils.timeElapsed(end_at-begin_at))
		c.execute("""SELECT oper, comment, at FROM comments WHERE ban_id=? ORDER BY at DESC""",(uid,))
		L = c.fetchall()
		if len(L):
			for com in L:
				(oper,comment,at) = com
				results.append('"%s" by %s on %s' % (comment,oper,floatToGMT(at)))
		c.execute("""SELECT ban_id,full FROM nicks WHERE ban_id=?""",(uid,))
		L = c.fetchall()
		if len(L):
			results.append('targeted:')
			for affected in L:
				(uid,mask) = affected
				results.append('- %s' % mask)
		c.close()
		return results
	
	def pending(self,irc,channel,mode,prefix,pattern,db):
		# returns active items for a channel mode
		if not channel or not mode or not prefix:
			return []
		if not ircdb.checkCapability(prefix, '%s,op' % channel):
			if prefix != irc.prefix:
				return []
		chan = self.getChan(irc,channel)
		items = chan.getItemsFor(mode)
		results = []
		r = []
		c = db.cursor()
		if len(items):
			for item in items:
				item = items[item]
				r.append([item.uid,item.mode,item.value,item.by,item.when,item.expire])
		r.sort(reverse=True)
		if len(r):
			for item in r:
				(uid,mode,value,by,when,expire) = item
				if pattern != None and not ircutils.hostmaskPatternEqual(pattern,by):
					continue
				c.execute("""SELECT oper, comment, at FROM comments WHERE ban_id=? ORDER BY at DESC LIMIT 1""",(uid,))
				L = c.fetchall()
				if len(L):
					(oper,comment,at) = L[0]
					message = '"%s" by %s' % (comment,oper)
				else: 
					message = ''
				if expire and expire != when:
					results.append('[#%s +%s %s by %s expires at %s] %s' % (uid,mode,value,by,floatToGMT(expire),message))
				else:
					results.append('[#%s +%s %s by %s setted on %s] %s' % (uid,mode,value,by,floatToGMT(when),message))	
		c.close()
		return results
	
	def log (self,irc,uid,prefix,db):
		# return log of affected users by a mode change
		if not uid or not prefix:
			return []
		c = db.cursor()
		c.execute("""SELECT channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE id=?""",(uid,))
		L = c.fetchall()
		if not len(L):
			c.close()
			return []
		(channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by) = L[0]
		if not ircdb.checkCapability(prefix, '%s,op' % channel):
			if prefix != irc.prefix:
				c.close()
				return []
		results = []
		c.execute("""SELECT full,log FROM nicks WHERE ban_id=?""",(uid,))
		L = c.fetchall()
		if len(L):
			for item in L:
				(full,log) = item
				results.append('for %s' % full)
				for line in log.split('\n'):
					results.append(line)
		else:
			results.append('no log found')
		c.close()
		return results
	
	def add (self,irc,channel,mode,value,seconds,prefix,db,logFunction,addOnly):
		# add new eIqb item
		if not ircdb.checkCapability(prefix,'%s,op' % channel):
			if prefix != irc.prefix:
				return False
		if not channel or not mode or not value or not prefix:
			return False
		c = db.cursor()
		c.execute("""SELECT id,oper FROM bans WHERE channel=? AND kind=? AND mask=? AND removed_at is NULL ORDER BY id LIMIT 1""",(channel,mode,value))
		L = c.fetchall()
		if len(L):
			# item exists, so edit it
			c.close()
			if addOnly:
				return False
			return self.edit(irc,channel,mode,value,seconds,prefix,db,logFunction,False)
		else:
			if channel in self.channels:
				chan = self.getChan(irc,channel)
				item = chan.getItem(mode,value)
				if not item:
					hash = '%s%s' % (mode,value)
					# prepare item update after being set ( we don't have id yet )
					chan.update[hash] = [mode,value,seconds,prefix]
					# enqueue mode changes
					chan.queue.enqueue(('+%s' % mode,value))
					return True
		return False
	
	def mark (self,irc,uid,message,prefix,db,logFunction):
		# won't use channel,mode,value, because Item may be removed already
		if not prefix or not message:
			return False
		c = db.cursor()
		c.execute("""SELECT id,channel,kind,mask FROM bans WHERE id=?""",(uid,))
		L = c.fetchall()
		b = False
		if len(L):	
			(uid,channel,kind,mask) = L[0]
			if not ircdb.checkCapability(prefix,'%s,op' % channel):
				if prefix != irc.prefix:
					c.close()
					return False
			current = time.time()
			c.execute("""INSERT INTO comments VALUES (?, ?, ?, ?)""",(uid,prefix,current,message))
			db.commit()
			logFunction(irc,channel,'[%s][#%s +%s %s] marked by %s: %s' % (channel,uid,kind,mask,prefix.split('!')[0],message))
			b = True
		c.close()
		return b
		
	def search (self,irc,pattern,prefix,db):
		# deep search inside database, 
		# results filtered depending prefix capability
		c = db.cursor()
		bans = {}
		results = []
		isOwner = ircdb.checkCapability(prefix, 'owner') or prefix == irc.prefix
		glob = '*%s*' % pattern
		like = '%'+pattern+'%'
		if pattern.startswith('$'):
			pattern = clearExtendedBanPattern(pattern)
			glob = '*%s*' % pattern
			like = '%'+pattern+'%'
		elif ircutils.isUserHostmask(pattern): 
			(n,i,h) = ircutils.splitHostmask(pattern)
			if n == '*':
				n = None
			if i == '*':
				i = None
			if h == '*':
				h = None
			items = [n,i,h]
			subpattern = ''
			for item in items:
				if item:
					subpattern = subpattern + '*' + item
			glob = '*%s*' % subpattern
			like = '%'+subpattern+'%'
			c.execute("""SELECT id, mask FROM bans ORDER BY id DESC""")
			items = c.fetchall()
			if len(items):
				for item in items:
					(uid,mask) = item
					if ircutils.hostmaskPatternEqual(pattern,mask):
						bans[uid] = uid
			c.execute("""SELECT ban_id, full FROM nicks ORDER BY ban_id DESC""")
			items = c.fetchall()
			if len(items):
				for item in items:
					(uid,full) = item
					if ircutils.hostmaskPatternEqual(pattern,full):
						bans[uid] = uid
		c.execute("""SELECT ban_id, full FROM nicks WHERE full GLOB ? OR full LIKE ? ORDER BY ban_id DESC""",(glob,like))
		items = c.fetchall()
		if len(items):
			for item in items:
				(uid,full) = item
				bans[uid] = uid
		c.execute("""SELECT id, mask FROM bans WHERE mask GLOB ? OR mask LIKE ? ORDER BY id DESC""",(glob,like))
		items = c.fetchall()
		if len(items):
			for item in items:
				(uid,full) = item
				bans[uid] = uid
		c.execute("""SELECT ban_id, comment FROM comments WHERE comment GLOB ? OR comment LIKE ? ORDER BY ban_id DESC""",(glob,like))
		items = c.fetchall()
		if len(items):
			for item in items:
				(uid,full) = item
				bans[uid] = uid
		if len(bans):
			for uid in bans:
				c.execute("""SELECT id, mask, kind, channel FROM bans WHERE id=? ORDER BY id DESC LIMIT 1""",(uid,))
				items = c.fetchall()
				for item in items:
					(uid,mask,kind,channel) = item
					if isOwner or ircdb.checkCapability(prefix, '%s,op' % channel) or prefix != irc.prefix:
						results.append([uid,mask,kind,channel])
		if len(results):
			results.sort(reverse=True)
			i = 0
			msgs = []
			while i < len(results):
				(uid,mask,kind,channel) = results[i]
				msgs.append('[#%s +%s %s in %s]' % (uid,kind,mask,channel))
				i = i+1
			return ', '.join(msgs)
		return 'nothing found'
	
	def submark (self,irc,channel,mode,value,message,prefix,db,logFunction):
		# add mark to an item which is not already in lists
		if not channel or not mode or not value or not prefix:
			return False
		if not ircdb.checkCapability(prefix,'%s,op' % channel):
			if prefix != irc.prefix:
				return False
		c = db.cursor()
		c.execute("""SELECT id,oper FROM bans WHERE channel=? AND kind=? AND mask=? AND removed_at is NULL ORDER BY id LIMIT 1""",(channel,mode,value))
		L = c.fetchall()
		if len(L):
			# item exists, so edit it
			(uid,oper) = L[0]
			c.close()
			return self.mark(irc,uid,message,prefix,db,logFunction)
		else:
			if channel in self.channels:
				chan = self.getChan(irc,channel)
				item = chan.getItem(mode,value)
				if not item:
					hash = '%s%s' % (mode,value)
					# prepare item update after being set ( we don't have id yet )
					chan.mark[hash] = [mode,value,message,prefix]
					return True
		return False
	
	def affect (self,irc,uid,prefix,db):
		# return affected users by a mode change
		if not uid or not prefix:
			return []
		c = db.cursor()
		c.execute("""SELECT channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE id=?""",(uid,))
		L = c.fetchall()
		if not len(L):
			c.close()
			return []
		(channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by) = L[0]
		if not ircdb.checkCapability(prefix, '%s,op' % channel):
			if prefix != irc.prefix:
				c.close()
				return []
		results = []
		c.execute("""SELECT full,log FROM nicks WHERE ban_id=?""",(uid,))
		L = c.fetchall()
		if len(L):
			for item in L:
				(full,log) = item
				results.append(full)
		else:
			results.append('nobody affected')
		c.close()
		return results
		
	
	def edit (self,irc,channel,mode,value,seconds,prefix,db,logFunction,massremoval):
		# edit eIqb duration
		if not channel or not mode or not value or not prefix:
			return False
		if not ircdb.checkCapability(prefix,'%s,op' % channel):
			if prefix != irc.prefix:
				return False
		c = db.cursor()
		c.execute("""SELECT id,channel,kind,mask,begin_at,end_at FROM bans WHERE channel=? AND kind=? AND mask=? AND removed_at is NULL ORDER BY id LIMIT 1""",(channel,mode,value))
		L = c.fetchall()
		b = False
		if len(L):
			(uid,channel,kind,mask,begin_at,end_at) = L[0]
			chan = self.getChan(irc,channel)
			current = time.time()
			if begin_at == end_at:
				text = 'was forever'
			else:
				text = 'ended [%s] for %s' % (floatToGMT(end_at),utils.timeElapsed(end_at-begin_at))
			if seconds < 0:
				newEnd = begin_at
				reason = 'never expires'
			else:
				newEnd = current+seconds
				reason = 'expires at [%s], for %s in total' % (floatToGMT(newEnd),utils.timeElapsed(newEnd-begin_at))
			text = '%s, now %s' % (text,reason)
			c.execute("""INSERT INTO comments VALUES (?, ?, ?, ?)""",(uid,prefix,current,text))
			c.execute("""UPDATE bans SET end_at=? WHERE id=?""", (newEnd,int(uid)))
			db.commit()
			if not massremoval:
				logFunction(irc,channel,'[%s][#%s +%s %s] edited by %s: %s' % (channel,uid,kind,mask,prefix.split('!')[0],reason))
			i = chan.getItem(kind,mask)
			if i:
				if newEnd == begin_at:
					i.expire = None
				else:
					i.expire = newEnd
			b = True
		c.close()
		return b
	
	def resync (self,irc,channel,mode,db,logFunction):
		# here sync mode lists, if items were removed when bot was offline, mark records as removed
		c = db.cursor()
		c.execute("""SELECT id,channel,mask FROM bans WHERE channel=? AND kind=?AND removed_at is NULL ORDER BY id""",(channel,mode))
		L = c.fetchall()
		current = time.time()
		commits = 0
		msgs = []
		if len(L):
			current = time.time()
			if channel in irc.state.channels:
				chan = self.getChan(irc,channel)
				if mode in chan.dones:
					for record in L:
						(uid,channel,mask) = record
						item = chan.getItem(mode,mask)
						if not item:
							c.execute("""UPDATE bans SET removed_at=?, removed_by=? WHERE id=?""", (current,'offline!offline@offline',int(uid)))
							commits = commits + 1
							msgs.append('[#%s %s]' % (uid,mask))
		if commits > 0:
			db.commit()
			logFunction(irc,channel,'[%s][%s] %s removed: %s' % (channel,mode,commits, ' '.join(msgs)))
		c.close()
		
	def getChan (self,irc,channel):
		if not channel or not irc:
			return None
		self.irc = irc
		if not channel in self.channels:
			self.channels[channel] = Chan (self,channel)
		return self.channels[channel]
			
	def getNick (self,irc,nick):
		if not nick or not irc:
			return None
		self.irc = irc
		if not nick in self.nicks:
			self.nicks[nick] = Nick(self.logsSize)
		return self.nicks[nick]
	
class Chan (object):
	# in memory and in database stores +eIqb list -ov
	# no user action from here, only ircd messages
	def __init__(self,ircd,name):
		object.__init__(self)
		self.ircd = ircd
		self.name = name
		self._lists = {}
		# queue contains (mode,valueOrNone) - ircutils.joinModes
		self.queue = utils.structures.smallqueue()
		# contains [modevalue] = [mode,value,seconds,prefix]
		self.update = {}
		# contains [modevalue] = [mode,value,message,prefix]
		self.mark = {}
		# contains IrcMsg ( mostly kick / fpart )
		self.action = utils.structures.smallqueue()
		# looking for eqIb list ends
		self.dones = []
		self.syn = False
		self.opAsked = False
		self.deopAsked = False
		# now stuff here is related to protection
		self.spam = {}
		self.repeatLogs = {}
		self.massPattern = {}
		
	def getItems (self):
		# [X][Item.value] is Item
		return self._lists
	
	def getItemsFor (self,mode):
		if not mode in self._lists:
			self._lists[mode] = {}
		return self._lists[mode]

	def addItem (self,mode,value,by,when,db):
		# eqIb(+*) (-ov) pattern prefix when 
		# mode : eqIb -ov + ?
		l = self.getItemsFor(mode)
		if not value in l:
			i = Item()
			i.channel = self.name
			i.mode = mode
			i.value = value
			uid = None
			expire = None
			c = db.cursor()
			c.execute("""SELECT id,oper,begin_at,end_at FROM bans WHERE channel=? AND kind=? AND mask=? AND removed_at is NULL ORDER BY id LIMIT 1""",(self.name,mode,value))
			L = c.fetchall()
			if len(L):
				# restoring stored informations, due to netsplit server's values may be wrong
				(uid,by,when,expire) = L[0]
				c.execute("""SELECT ban_id,full FROM nicks WHERE ban_id=?""",(uid,))
				L = c.fetchall()
				if len(L):
					for item in L:
						(uid,full) = item
						i.affects.append(full)
			else:
				# if begin_at == end_at --> that means forever
				c.execute("""INSERT INTO bans VALUES (NULL, ?, ?, ?, ?, ?, ?,NULL, NULL)""", (self.name,by,mode,value,when,when))
				db.commit()
				uid = c.lastrowid
				# leave channel's users list management to supybot
				ns = []
				if self.name in self.ircd.irc.state.channels:
					for nick in self.ircd.irc.state.channels[self.name].users:
						if nick in self.ircd.nicks:
							n = self.ircd.getNick(self.ircd.irc,nick)
							m = match(value,n)
							if m:
								i.affects.append(n.prefix)
								# insert logs
								index = 0
								logs = []
								logs.append('%s matched by %s' % (n,m))
								for line in n.logs:
									(ts,target,message) = n.logs[index]
									index += 1
									if target == self.name or target == 'ALL':
										logs.append('[%s] %s' % (floatToGMT(ts),message))
								c.execute("""INSERT INTO nicks VALUES (?, ?, ?, ?)""",(uid,value,n.prefix,'\n'.join(logs)))
								ns.append([n,m])
				if len(ns):
					db.commit()
			c.close()
			i.uid = uid
			i.by = by
			i.when = when
			i.expire = expire
			l[value] = i
		return l[value]
		
	def getItem (self,mode,value):
		if mode in self._lists:
			if value in self._lists[mode]:
				return self._lists[mode][value]
		return None
		
	def removeItem (self,mode,value,by,db):
		# flag item as removed in database
		c = db.cursor()
		c.execute("""SELECT id,oper,begin_at,end_at FROM bans WHERE channel=? AND kind=? AND mask=? AND removed_at is NULL ORDER BY id LIMIT 1""",(self.name,mode,value))
		L = c.fetchall()
		removed_at = time.time()
		i = self.getItem(mode,value)
		if len(L):
			(uid,by,when,expire) = L[0]
			c.execute("""UPDATE bans SET removed_at=?, removed_by=? WHERE id=?""", (removed_at,by,int(uid)))
			db.commit()
			c.close()
			if i:
				i.uid = uid
				i.mode = mode
				i.by = by
				i.when = when
				i.expire = expire				
		# item can be None, if someone typoed a -eqbI value
		if i:
			self._lists[mode].pop(value)
			
			i.removed_by = by
			i.removed_at = removed_at
		return i
	
class Item (object):
	def __init__(self):
		object.__init__(self)
		self.channel = None
		self.mode = None
		self.value = None
		self.by = None
		self.when = None
		self.uid = None
		self.expire = None
		self.removed_at = None
		self.removed_by = None
		self.asked = False
		self.affects = []
		
	def __repr__(self):
		end = self.expire
		if self.when == self.expire:
			end = None
		return 'Item(%s [%s][%s] by %s on %s, expire on %s, removed %s by %s)' % (self.uid,self.mode,self.value,self.by,floatToGMT(self.when),floatToGMT(end),floatToGMT(self.removed_at),self.removed_by)
	
class Nick (object):
	def __init__(self,logSize):
		object.__init__(self)
		self.prefix = None
		self.ip = None
		self.realname = None
		self.account = None
		self.logs = utils.structures.MaxLengthQueue(logSize)
		# log format :
		# target can be a channel, or 'ALL' when it's related to nick itself ( account changes, nick changes, host changes, etc )
		# [float(timestamp),target,message]
	
	def setPrefix (self,prefix):
		if not prefix == self.prefix:
			self.prefix = prefix
			# recompute ip
			if self.prefix:
				matchHostmask(self.prefix,self)
				getBestPattern(self)
		return self
	
	def setIp (self,ip):
		if ip != None and not ip == self.ip and not ip == '255.255.255.255' and isIp(ip):
			self.ip = ip
		return self
	
	def setAccount (self,account):
		self.account = account
		return self
		
	def setRealname (self,realname):
		self.realname = realname
		return self
		
	def addLog (self,target,message):
		self.logs.enqueue([time.time(),target,message])
		return self
	
	def __repr__(self):
		return '%s ip:%s $a:%s $r:%s' % (self.prefix,self.ip,self.account,self.realname)

# Taken from plugins.Time.seconds
def getTs (irc, msg, args, state):
	"""[<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s]
	
	Returns the number of seconds in the number of <years>, <weeks>,
	<days>, <hours>, <minutes>, and <seconds> given.  An example usage is
	"seconds 2h 30m", which would return 9000, which is '3600*2 + 30*60'.
	Useful for scheduling events at a given number of seconds in the
	future.
	"""
	# here there is some glich / ugly hack to allow any('getTs'), with rest('test') after ... 
	# TODO checks that bot can't kill itself with loop 
	seconds = -1
	for arg in args:
		if not arg or arg[-1] not in 'ywdhms':
			try:
				n = int(args[0])
				state.args.append(n)
				args.pop(0)
			except:
				if len(args) > 1:
					if seconds != -1:
						args.pop(0)
					state.args.append(float(seconds))
					raise callbacks.ArgumentError
				else:
					raise callbacks.ArgumentError
			return
		(s, kind) = arg[:-1], arg[-1]
		try:
			i = int(s)
		except ValueError:
			raise callbacks.ArgumentError
			return
		if kind == 'y':
			seconds += i*31536000
		elif kind == 'w':
			seconds += i*604800
		elif kind == 'd':
			seconds += i*86400
		elif kind == 'h':
			seconds += i*3600
		elif kind == 'm':
			seconds += i*60
		elif kind == 's':
			seconds += i
	args.pop(0)
	state.args.append(float(seconds))

addConverter('getTs', getTs)

import threading
import supybot.world as world

def getDuration (seconds):
	if not seconds or not len(seconds):
		return -1
	return seconds[0]

class ChanTracker(callbacks.Plugin,plugins.ChannelDBHandler):
	"""This plugin keeps records of channel mode changes and permits to manage them over time
	it also have some channel protection features
	"""
	threaded = True
	noIgnore = True
	
	def __init__(self, irc):
		self.__parent = super(ChanTracker, self)
		self.__parent.__init__(irc)
		callbacks.Plugin.__init__(self, irc)
		plugins.ChannelDBHandler.__init__(self)
		self.lastTickle = time.time()-self.registryValue('pool')
		self.forceTickle = True
		self._ircs = {}
		self.getIrc(irc)
		self.recaps = re.compile("[A-Z]")
	
	def edit (self,irc,msg,args,user,ids,seconds):
		"""<id> [,<id>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1>] means forever

		change expiration of some active modes"""
		i = self.getIrc(irc)
		b = True
		for id in ids:
			item = i.getItem(irc,id)
			if item:
				b = b and i.edit(irc,item.channel,item.mode,item.value,getDuration(seconds),msg.prefix,self.getDb(irc.network),self._logChan,False)
			else:
				b = False
		if not msg.nick == irc.nick:
			if b:
				irc.replySuccess()
			else:
				irc.error('no item found or not enough rights')
		self.forceTickle = True
		self._tickle(irc)
	edit = wrap(edit,['user',commalist('int'),any('getTs')])
	
	def info (self,irc,msg,args,user,id):
		"""<id>

		summary of a mode change"""
		i = self.getIrc(irc)
		results = i.info(irc,id,msg.prefix,self.getDb(irc.network))
		if len(results):
			for line in results:
				irc.queueMsg(ircmsgs.privmsg(msg.nick,line))
		else:
			irc.error('no item found or not enough rights')
		self._tickle(irc)
	info = wrap(info,['user','int'])
	
	def detail (self,irc,msg,args,user,uid):
		"""<id>

		logs of a mode change"""
		i = self.getIrc(irc)
		results = i.log (irc,uid,msg.prefix,self.getDb(irc.network))
		if len(results):
			for line in results:
				irc.queueMsg(ircmsgs.privmsg(msg.nick,line))
		else:
			irc.error('no item found or not enough rights')
		self._tickle(irc)
	detail = wrap(detail,['user','int'])
	
	def affect (self,irc,msg,args,user,uid):
		"""<id>

		list users affected by a mode change"""
		i = self.getIrc(irc)
		results = i.affect (irc,uid,msg.prefix,self.getDb(irc.network))
		if len(results):
			for line in results:
				irc.queueMsg(ircmsgs.privmsg(msg.nick,line))
		else:
			irc.error('no item found or not enough rights')
		self._tickle(irc)
	affect = wrap(affect, ['user','int'])
	
	def mark(self,irc,msg,args,user,ids,message):
		"""<id> [,<id>]

		add comment on a mode change"""
		i = self.getIrc(irc)
		b = True
		for id in ids:
			b = b and i.mark(irc,id,message,msg.prefix,self.getDb(irc.network),self._logChan)
		if not msg.nick == irc.nick:
			if b:
				irc.replySuccess()
			else:
				irc.error('item not found or not enough rights')
		self.forceTickle = True
		self._tickle(irc)
	mark = wrap(mark,['user',commalist('int'),'text'])
	
	def query (self,irc,msg,args,user,text):
		"""<pattern|hostmask>

		returns known mode changes with deep search"""
		# method renamed due to conflict with Config.search
		i = self.getIrc(irc)
		irc.reply(i.search(irc,text,msg.prefix,self.getDb(irc.network)))
	query = wrap(query,['user','text'])
	
	def pending (self, irc, msg, args, channel, mode, pattern):
		"""[<channel>] [<mode>] [<hostmask>]

		returns active items for mode if given otherwise all modes are returned, if hostmask given, filtered by oper"""
		i = self.getIrc(irc)
		if not mode:
			results = []
			modes = self.registryValue('modesToAskWhenOpped') + self.registryValue('modesToAsk')
			for m in modes:
				r = i.pending(irc,channel,m,msg.prefix,pattern,self.getDb(irc.network))
				if len(r):
					for line in r:
						results.append(line)
		else:
			results = i.pending(irc,channel,mode,msg.prefix,pattern,self.getDb(irc.network))
		if len(results):
			for line in results:
				irc.queueMsg(ircmsgs.privmsg(msg.nick,line))
		else:
			irc.error('no results')
	pending = wrap(pending,['op',additional('letter'),optional('hostmask')])
	
	def do (self,irc,msg,args,channel,mode,items,seconds,reason):
		"""[<channel>] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1> or empty means forever] <reason>

		+mode targets for duration reason is mandatory"""
		if mode in self.registryValue('modesToAsk') or mode in self.registryValue('modesToAskWhenOpped'):
			b = self._adds(irc,msg,args,channel,mode,items,getDuration(seconds),reason)
			if not msg.nick == irc.nick:
				# why msg.nick == irc.nick, it because with that it can be used with BanHammer plugin
				if b:
					irc.replySuccess()
					return
				irc.error('item already active or not enough rights')
		else:
			irc.error('selected mode is not supported by config')
	do = wrap(do,['op','letter',commalist('something'),any('getTs',True),rest('text')])
	
	def q (self,irc,msg,args,channel,items,seconds,reason):
		"""[<channel>] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1> or empty means forever] <reason>

		+q targets for duration reason is mandatory"""
		b = self._adds(irc,msg,args,channel,'q',items,getDuration(seconds),reason)
		if not msg.nick == irc.nick:
			if b:
				irc.replySuccess()
				return
			irc.error('item already active or not enough rights')
	q = wrap(q,['op',commalist('something'),any('getTs',True),rest('text')])
	
	def b (self, irc, msg, args, channel, items, seconds,reason):
		"""[<channel>] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1> or empty means forever] <reason>

		+b targets for duration reason is mandatory"""
		b = self._adds(irc,msg,args,channel,'b',items,getDuration(seconds),reason)
		if not msg.nick == irc.nick:
			if b:
				irc.replySuccess()
				return
			irc.error('item already active or not enough rights')
	b = wrap(b,['op',commalist('something'),any('getTs',True),rest('text')])
	
	def i (self, irc, msg, args, channel, items, seconds):
		"""[<channel>] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1> or empty means forever] <reason>

		+I targets for duration reason is mandatory"""
		b = self._adds(irc,msg,args,channel,'I',items,getDuration(seconds),reason)
		if not msg.nick == irc.nick:
			if b:
				irc.replySuccess()
				return
			irc.error('item already active or not enough rights')
	i = wrap(i,['op',commalist('something'),any('getTs',True),rest('text')])
	
	def e (self, irc, msg, args, channel, items,seconds,reason):
		"""[<channel>] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1> or empty means forever] <reason>

		+e targets for duration reason is mandatory"""
		b = self._adds(irc,msg,args,channel,'e',items,getDuration(seconds),reason)
		if not msg.nick == irc.nick:
			if b:
				irc.replySuccess()
				return
			irc.error('item already active or not enough rights')
	e = wrap(e,['op',commalist('something'),any('getTs'),rest('text')])
	
	def undo (self, irc, msg, args, channel, mode, items):
		"""[<channel>] <nick|hostmask|*> [<nick|hostmask|*>]

		sets -q on them, if * found, remove them all"""
		b = self._removes(irc,msg,args,channel,mode,items)
		if not msg.nick == irc.nick:
			if b:
				irc.replySuccess()
				return
			irc.error('item not found or not enough rights or unsupported mode')
	undo = wrap(undo,['op','letter',many('something')])
	
	def uq (self, irc, msg, args, channel, items):
		"""[<channel>] <nick|hostmask|*> [<nick|hostmask|*>]

		sets -q on them, if * found, remove them all"""
		b = self._removes(irc,msg,args,channel,'q',items)
		if not msg.nick == irc.nick:
			if b:
				irc.replySuccess()
				return
			irc.error('item not found or not enough rights or unsupported mode')
	uq = wrap(uq,['op',many('something')])
	
	def ub (self, irc, msg, args, channel, items):
		"""[<channel>] <nick|hostmask|*> [<nick|hostmask>]

		sets -b on them, if * found, remove them all"""
		b = self._removes(irc,msg,args,channel,'b',items)
		if not msg.nick == irc.nick:
			if b:
				irc.replySuccess()
				return
			irc.error('item not found or not enough rights or unsupported mode')
	ub = wrap(ub,['op',many('something')])
	
	def ui (self, irc, msg, args, channel, items):
		"""[<channel>] <nick|hostmask|*> [<nick|hostmask|*>]

		sets -I on them, if * found, remove them all"""
		b = self._removes(irc,msg,args,channel,'I',items)
		if not msg.nick == irc.nick:
			if b:
				irc.replySuccess()
				return
			irc.error('item not found or not enough rights or unsupported mode')
	ui = wrap(ui,['op',many('something')])
	
	def ue (self, irc, msg, args, channel, items):
		"""[<channel>] <nick|hostmask|*> [<nick|hostmask|*>]

		sets -e on them, if * found, remove them all"""
		b = self._removes(irc,msg,args,channel,'e',items)
		if not msg.nick == irc.nick:
			if b:
				irc.replySuccess()
				return
			irc.error('item not found or not enough rights or unsupported mode')
	ue = wrap(ue,['op',many('something')])
	
	def check (self,irc,msg,args,channel,pattern):
		"""[<channel>] <pattern> 

		returns a list of affected users by a pattern"""
		if ircutils.isUserHostmask(pattern) or pattern.startswith('$'):
			results = []
			i = self.getIrc(irc)
			for nick in irc.state.channels[channel].users.keys():
				if nick in i.nicks:
					n = self.getNick(irc,nick)
					m = match(pattern,n)
					if m:
						results.append(nick)
			if len(results):
				irc.reply(', '.join(results))
			else:
				irc.error('nothing found')
		else:
			irc.error('invalid pattern')
	check = wrap (check,['op','text'])
	
	def getmask (self,irc,msg,args,prefix):
		"""<nick|hostmask> 

		returns a list of hostmask's pattern, best first, mostly used for debug"""
		# returns patterns for a given nick
		i = self.getIrc(irc)
		if prefix in i.nicks:
			irc.reply(', '.join(getBestPattern(self.getNick(irc,prefix))))
		else:
			n = Nick(0)
			if prefix.find('#') != -1:
				a = prefix.split('#')
				username = a[1]
				prefix = a[0]
				n.setPrefix(prefix)
				n.setUsername(username)
			else:
				n.setPrefix(prefix)
			if ircutils.isUserHostmask(prefix):
				irc.reply(', '.join(getBestPattern(n)))
				return
			irc.error('nick not found')
	getmask = wrap(getmask,['owner','text'])
	
	def _adds (self,irc,msg,args,channel,mode,items,duration,reason):
		i = self.getIrc(irc)
		targets = []
		if mode in self.registryValue('modesToAsk') or mode in self.registryValue('modesToAskWhenOpped'):
			for item in items:
				if ircutils.isUserHostmask(item) or item.startswith('$'):
					targets.append(item)
				elif channel in irc.state.channels and item in irc.state.channels[channel].users:
					n = self.getNick(irc,item)
					targets.append(getBestPattern(n)[0])
		n = 0
		for item in targets:
			if i.add(irc,channel,mode,item,duration,msg.prefix,self.getDb(irc.network),self._logChan,False):
				if reason:
					i.submark(irc,channel,mode,item,reason,msg.prefix,self.getDb(irc.network),self._logChan)
				n = n+1
		self.forceTickle = True
		self._tickle(irc)
		return len(items) == n
	
	def _removes (self,irc,msg,args,channel,mode,items):
		i = self.getIrc(irc)
		chan = self.getChan(irc,channel)
		targets = []
		massremove = False
		n = 0
		if mode in self.registryValue('modesToAsk') or mode in self.registryValue('modesToAskWhenOpped'):
			for item in items:
				if ircutils.isUserHostmask(item) or item.startswith('$'):
					targets.append(item)
				elif channel in irc.state.channels and item in irc.state.channels[channel].users:
					n = self.getNick(irc,item)
					L = chan.getItemsFor(mode)
					# here we check active items against Nick and add everything pattern which matchs him
					for pattern in L:
						m = match(pattern,n)
						if m:
							targets.append(pattern)
				elif item == '*':
					massremove = True
					if channel in irc.state.channels.keys():
						L = chan.getItemsFor(mode)
						for pattern in L:
							targets.append(pattern)
			for item in targets:
				if i.edit(irc,channel,mode,item,0,msg.prefix,self.getDb(irc.network),self._logChan,massremove):
					n = n + 1
		self.forceTickle = True
		self._tickle(irc)
		return len(items) == n or massremove
	
	def getIrc (self,irc):
		# init irc db
		if not irc in self._ircs:
			i = self._ircs[irc] = Ircd (irc,self.registryValue('logsSize'))
			# restore CAP, if needed, needed to track account (account-notify) ang gecos (extended-join)
			# see config of this plugin
			irc.queueMsg(ircmsgs.IrcMsg('CAP LS'))
		return self._ircs[irc]
	
	def getChan (self,irc,channel):
		i = self.getIrc(irc)
		if not channel in i.channels:
			# restore channel state, loads lists
			modesToAsk = ''.join(self.registryValue('modesToAsk'))
			modesWhenOpped = ''.join(self.registryValue('modesToAskWhenOpped'))
			if channel in irc.state.channels:
				if irc.nick in irc.state.channels[channel].ops and len(modesWhenOpped):
					i.queue.enqueue(ircmsgs.IrcMsg('MODE %s %s' % (channel,modesWhenOpped)))
				if len(modesToAsk):
					i.queue.enqueue(ircmsgs.IrcMsg('MODE %s %s' % (channel,modesToAsk)))
				# loads extended who
				i.queue.enqueue(ircmsgs.IrcMsg('WHO ' + channel +' %tnuhiar,42'))
				# fallback, TODO maybe uneeded as supybot do it by itself, but necessary on plugin reload ...
				i.queue.enqueue(ircmsgs.IrcMsg('WHO %s' % channel))
		return i.getChan (irc,channel)
	
	def getNick (self,irc,nick):
		return self.getIrc (irc).getNick (irc,nick)	
	
	def makeDb(self, filename):
		"""Create a database and connect to it."""
		if os.path.exists(filename):
			db = sqlite3.connect(filename)
			db.text_factory = str
			return db
		db = sqlite3.connect(filename)
		db.text_factory = str
		c = db.cursor()
		c.execute("""CREATE TABLE bans (
				id INTEGER PRIMARY KEY,
				channel VARCHAR(100) NOT NULL,
				oper VARCHAR(1000) NOT NULL,
				kind VARCHAR(1) NOT NULL,
				mask VARCHAR(1000) NOT NULL,
				begin_at TIMESTAMP NOT NULL,
				end_at TIMESTAMP NOT NULL,
				removed_at TIMESTAMP,
				removed_by VARCHAR(1000)
				)""")
		c.execute("""CREATE TABLE nicks (
				ban_id INTEGER,
				ban VARCHAR(1000) NOT NULL,
				full VARCHAR(1000) NOT NULL,
				log TEXT NOT NULL
				)""")
		c.execute("""CREATE TABLE comments (
				ban_id INTEGER,
				oper VARCHAR(1000) NOT NULL,
				at TIMESTAMP NOT NULL,
				comment TEXT NOT NULL
				)""")
		db.commit()
		return db
	
	def getDb(self, irc):
		"""Use this to get a database for a specific irc."""
		currentThread = threading.currentThread()
		if irc not in self.dbCache and currentThread == world.mainThread:
			self.dbCache[irc] = self.makeDb(self.makeFilename(irc))
		if currentThread != world.mainThread:
			db = self.makeDb(self.makeFilename(irc))
		else:
			db = self.dbCache[irc]
		db.isolation_level = None
		return db
	
	def doPong (self,irc,msg):
		self._tickle(irc)
	
	def doPing (self,irc,msg):
		self._tickle(irc)
	
	def _sendModes (self, irc, modes, f):
		numModes = irc.state.supported.get('modes', 1)
		ircd = self.getIrc(irc)
		for i in range(0, len(modes), numModes):
			ircd.queue.enqueue(f(modes[i:i + numModes]))
	
	def _tickle (self,irc):
		# Called each time messages are received from irc, it avoid using schedulers which can fail silency
		# For performance, that may be change in future ...
		t = time.time()
		if not self.forceTickle:
			pool = self.registryValue('pool')
			if pool > 0:
				if self.lastTickle+pool > t:
					return
				self.lastTickle = t
		i = self.getIrc(irc)
		retickle = False
		# send waiting msgs, here we mostly got kick messages
		while len(i.queue):
			# sendMsg vs queueMsg 
			irc.sendMsg(i.queue.dequeue())
		def f(L):
			return ircmsgs.modes(channel,L)
		for channel in irc.state.channels.keys():
			chan = self.getChan(irc,channel)
			# check expired items
			for mode in chan.getItems().keys():
				for value in chan._lists[mode].keys():
					item = chan._lists[mode][value]
					if item.expire != None and item.expire != item.when and not item.asked and item.expire <= t:
						chan.queue.enqueue(('-'+item.mode,item.value))
						# avoid adding it multi times until servers returns changes
						item.asked = True
						retickle = True
			# dequeue pending actions
			if not irc.nick in irc.state.channels[channel].ops and not chan.opAsked and self.registryValue('keepOp',channel=channel) and chan.syn:
				# chan.syn is necessary, otherwise, bot can't call owner if rights missed ( see doNotice )
				chan.opAsked = True
				irc.sendMsg(ircmsgs.IrcMsg(self.registryValue('opCommand') % (channel,irc.nick)))
				retickle = True
			if len(chan.queue):
				if not irc.nick in irc.state.channels[channel].ops and not chan.opAsked:
					# pending actions and not opped
					chan.opAsked = True
					irc.sendMsg(ircmsgs.IrcMsg(self.registryValue('opCommand') % (channel,irc.nick)))
					retickle = True
				elif irc.nick in irc.state.channels[channel].ops:
					L = []
					while len(chan.queue):
						L.append(chan.queue.pop())
					# remove duplicates ( should not happens but .. )
					S = Set(L)
					r = []
					for item in L:
						r.append(item)
					if len(r):
						# create IrcMsg
						self._sendModes(irc,r,f)
			if not len(i.queue) and not len(chan.queue) and irc.nick in irc.state.channels[channel].ops and not self.registryValue('keepOp',channel=channel) and not chan.deopAsked:
				# no more actions, no op needed
				chan.deopAsked = True
				def deop ():
					# due to issues with op devoiced himself before applying -v-o on targeted users, must delay a bit here ...
					chan.queue.enqueue(('-o',irc.nick))
					retickle = True
					self._tickle(irc)
				schedule.addEvent(deop,time.time()+7)
				retickle = True
		# send waiting msgs
		while len(i.queue):
			# sendMsg vs queueMsg 
			irc.sendMsg(i.queue.dequeue())
		for channel in irc.state.channels.keys():
			chan = self.getChan(irc,channel)
			# check items to update - duration
			# that allows to set mode, and apply duration to Item created after mode changes
			# otherwise, we should create db records before applying mode changes ... which, well don't do that :p
			if len(chan.update):
				overexpire = self.registryValue('autoExpire',channel=channel)
				if overexpire > 0:
					# won't override duration pushed by someone else if default is forever
					# [mode,value,seconds,prefix]
					L = []
					for update in chan.update.keys():
						L.append(chan.update[update])
					o = {}
					index = 0
					for k in L:
						(m,value,expire,prefix) = L[index]
						if expire == -1 or expire == None:
							if overexpire != expire:
								chan.update['%s%s' % (m,value)] = [m,value,overexpire,irc.prefix]
						index = index + 1
				L = []
				for update in chan.update.keys():
					L.append(chan.update[update])
				for update in L:
					(m,value,expire,prefix) = update
					item = chan.getItem(m,value)
					if item and item.expire != expire:
						b = i.edit(irc,item.channel,item.mode,item.value,expire,prefix,self.getDb(irc.network),self._logChan,False)
						key = '%s%s' % (m,value)
						del chan.update[key]
						retickle = True
						
			# update marks
			if len(chan.mark):
				L = []
				for mark in chan.mark.keys():
					L.append(chan.mark[mark])
				for mark in L:
					(m,value,reason,prefix) = mark
					item = chan.getItem(m,value)
					if item:
						i.mark(irc,item.uid,reason,prefix,self.getDb(irc.network),self._logChan)
						key = '%s%s' % (item.mode,value)
						del chan.mark[key]
		
		if retickle:
			self.forceTickle = True
		else:
			self.forceTickle = False
	
	def _addChanModeItem (self,irc,channel,mode,value,prefix,date):
		# bqeI* -ov
		if irc.isChannel(channel) and channel in irc.state.channels:
			chan = self.getChan(irc,channel)
			chan.addItem(mode,value,prefix,date,self.getDb(irc.network))
	
	def _endList (self,irc,msg,channel,mode):
		if irc.isChannel(channel) and channel in irc.state.channels:
			chan = self.getChan(irc,channel)
			b = False
			if not mode in chan.dones:
				chan.dones.append(mode)
				b = True
			i = self.getIrc(irc)
			i.resync(irc,channel,mode,self.getDb(irc.network),self._logChan)
			if b:
				self._logChan(irc,channel,"[%s][%s] %s items parsed, ready %s" % (channel,mode,len(chan.getItemsFor(mode)),''.join(chan.dones)))
		self._tickle(irc)
	
	def do346 (self,irc,msg):
		# /mode #channel I
		self._addChanModeItem(irc,msg.args[1],'I',msg.args[2],msg.args[3],msg.args[4])
	
	def do347 (self,irc,msg):
		# end of I list
		self._endList(irc,msg,msg.args[1],'I')
	
	def do348 (self,irc,msg):
		# /mode #channel e
		self._addChanModeItem(irc,msg.args[1],'e',msg.args[2],msg.args[3],msg.args[4])
	
	def do349 (self,irc,msg):
		# end of e list
		self._endList(irc,msg,msg.args[1],'e')
	
	def do367 (self,irc,msg):
		# /mode #channel b
		self._addChanModeItem(irc,msg.args[1],'b',msg.args[2],msg.args[3],msg.args[4])
		
	def do368 (self,irc,msg):
		# end of b list
		self._endList(irc,msg,msg.args[1],'b')
	
	def do728 (self,irc,msg):
		# extended channel's list ( q atm )
		self._addChanModeItem(irc,msg.args[1],msg.args[2],msg.args[3],msg.args[4],msg.args[5])
	
	def do729 (self,irc,msg):
		# end of extended list ( q )
		self._endList(irc,msg,msg.args[1],msg.args[2])
	
	def do352(self, irc, msg):
		# WHO $channel
		(nick, ident, host) = (msg.args[5], msg.args[2], msg.args[3])
		n = self.getNick(irc,nick)
		n.setPrefix('%s!%s@%s' % (nick,ident,host))
		# channel = msg.args[1]
	
	def do329 (self,irc,msg):
		# channel timestamp
		channel = msg.args[1]
		self._tickle(irc)
	
	def do354 (self,irc,msg):
		# WHO $channel %tnuhiar,42
		# irc.nick 42 ident ip host nick account realname
		if len(msg.args) == 8 and msg.args[1] == '42':
			(garbage,digit,ident,ip,host,nick,account,realname) = msg.args
			if account == '0':
				account = None
			n = self.getNick(irc,nick)
			n.setPrefix('%s!%s@%s' % (nick,ident,host))
			n.setIp(ip)
			n.setAccount(account)
			n.setRealname(realname)
			#channel = msg.args[1]
		self._tickle(irc)
	
	def do315 (self,irc,msg):
		# end of extended WHO $channel
		channel = msg.args[1]
		if irc.isChannel(channel) and channel in irc.state.channels:
			chan = self.getChan(irc,channel)
			if not chan.syn:
				# this flag is mostly used to wait for the full sync before moaming on owners when something wrong happened
				# like not enough rights to take op
				chan.syn = True
		self._tickle(irc)
	
	def _logChan (self,irc,channel,message):
		if channel in irc.state.channels:
			logChannel = self.registryValue('logChannel',channel=channel)
			if logChannel in irc.state.channels:
				irc.queueMsg(ircmsgs.privmsg(logChannel,message))
	
	def doJoin (self,irc,msg):
		channels = msg.args[0].split(',')
		n = self.getNick(irc,msg.nick)
		i = self.getIrc(irc)
		n.setPrefix(msg.prefix)
		if 'LIST' in i.caps and 'extended-join' in i.caps['LIST'] and len(msg.args) == 3:
			n.setRealname(msg.args[2])
			n.setAccount(msg.args[1])
		best = getBestPattern(n)[0]
		for channel in channels:
			if ircutils.isChannel(channel) and channel in irc.state.channels:
				chan = self.getChan(irc,channel)
				n.addLog(channel,'has joined')
				if best:
					isCycle = self._isSomething(irc,channel,best,'cycle')
					if isCycle:
						isBad = self._isSomething(irc,channel,best,'bad')
						kind = None
						if isBad:
							kind = 'bad'
						else:
							kind = 'cycle'
						mode = self.registryValue('%sMode' % kind,channel=channel)
						if len(mode) > 1:
							mode = mode[0]
						duration = self.registryValue('%sDuration' % kind,channel=channel)
						comment = self.registryValue('%sComment' % kind,channel=channel)
						self._act(irc,channel,mode,best,duration,comment)
						self.forceTickle = True
		if msg.nick == irc.nick:
			self.forceTickle = True
		self._tickle(irc)
	
	def doPart (self,irc,msg):
		isBot = msg.nick == irc.nick
		channels = msg.args[0].split(',')
		i = self.getIrc(irc)
		n = None
		if msg.nick in i.nicks:
			n = self.getNick(irc,msg.nick)
		reason = ''
		if len(msg.args) == 2:
			reason = msg.args[1].lstrip().rstrip()
		canRemove = True
		for channel in channels:
			if ircutils.isChannel(channel) and channel in irc.state.channels:
				if isBot and channel in i.channels:
					del i.channels[channel]
					continue
				if len(reason):
					n.addLog(channel,'has left [%s]' % (reason))
					if reason.startswith('requested by'):
						self._logChan(irc,channel,'[%s] %s has left (%s)' % (channel,msg.prefix,reason))
				else:
					n.addLog(channel,'has left')
				if not isBot:
					if msg.nick in irc.state.channels[channel].users:
						canRemove = False
		if canRemove:
			self._rmNick(irc,n)
		self._tickle(irc)
	
	def doKick (self,irc,msg):
		if len(msg.args) == 3:
			(channel,target,reason) = msg.args
		else:
			(channel,target) = msg.args
			reason = ''
		isBot = target == irc.nick
		if isBot:
			if ircutils.isChannel(channel) and channel in i.channels:
				del i.channels[channel]
				return
		n = self.getNick(irc,target)
		n.addLog(channel,'kicked by %s (%s)' % (msg.prefix,reason))
		self._logChan(irc,channel,'[%s] %s kicked by %s (%s)' % (channel,target,msg.prefix,reason))
		self._tickle(irc)

	def _rmNick (self,irc,n):
		def nrm():
			patterns = getPattern(n)
			i = self.getIrc(irc)
			if not len(patterns):
				return
			found = False
			(nick,ident,hostmask) = ircutils.splitUserHostmask(n.prefix)
			for channel in irc.state.channels:
				if nick in irc.state.channels[channel].users:
					 found = True
			if not found:
				if nick in i.nicks:
					del i.nicks[nick]
				best = patterns[0]
				for channel in irc.state.channels:
					if channel in i.channels:
						chan = i.getChan(channel)
						if best in chan.repeatLogs:
							del chan.repeatLogs[best]
		schedule.addEvent(nrm,time.time()+300)
	
	def doQuit (self,irc,msg):
		isBot = msg.nick == irc.nick
		reason = None
		if len(msg.args) == 1:
			reason = msg.args[0].lstrip().rstrip()
		removeNick = True
		if not isBot:
			n = self.getNick(irc,msg.nick)
			if reason:
				n.addLog('ALL','has quit [%s]' % reason)
			else:
				n.addLog('ALL','has quit')
			if reason and reason in ['Changing host','Excess Flood','MaxSendQ']:
				removeNick = False
			elif reason and reason.startswith('Killed (') or reason.startswith('K-Lined'):
				if not reason.find('Nickname regained by services') != -1:
					for channel in irc.state.channels:
						for nick in irc.state.channels[channel].users:
							if nick == msg.nick:
								self._logChan(irc,channel,'[%s] %s has quit (%s)' % (channel,msg.prefix,reason))
			if removeNick:
				i = self.getIrc(irc)
				if msg.nick in i.nicks:
					n = i.nicks[msg.nick]
					self._rmNick(irc,n)
			self._tickle(irc)
	
	def doNick (self,irc,msg):
		oldNick = msg.prefix.split('!')[0]
		newNick = msg.args[0]
		i = self.getIrc (irc)
		n = None
		if oldNick in i.nicks:
			n = self.getNick(irc,oldNick)
			i.nicks.pop(oldNick)
			if n.prefix:
				prefixNew = '%s!%s' % (newNick,n.prefix.split('!')[1:])
				n.setPrefix(prefixNew)
			i.nicks[newNick] = n
			n = self.getNick(irc,newNick)
			n.addLog('ALL','%s is now known as %s' % (oldNick,newNick))
			best = None
			patterns = getBestPattern(n)
			if len(patterns):
				best = patterns[0]
			if not best:
				return
			for channel in irc.state.channels:
				if newNick in irc.state.channels[channel].users:
					isNick = self._isSomething(irc,channel,best,'nick')
					if isNick:
						isBad = self._isBad(irc,channel,best)
						kind = None
						if isBad:
							kind = 'bad'
						else:
							kind = 'nick'
						mode = self.registryValue('%sMode' % kind,channel=channel)
						if len(mode) > 1:
							mode = mode[0]
						duration = self.registryValue('%sDuration' % kind,channel=channel)
						comment = self.registryValue('%sComment' % kind,channel=channel)
						self._act(irc,channel,mode,best,duration,comment)
						self.forceTickle = True
		self._tickle(irc)
	
	def doCap (self,irc,msg):
		# handles CAP messages
		i = self.getIrc(irc)
		command = msg.args[1]
		l = msg.args[2].split(' ')
		if command == 'LS':
			# retreived supported CAP
			i.caps['LS'] = l
			# checking actives CAP, reload, etc
			irc.queueMsg(ircmsgs.IrcMsg('CAP LIST'))
		elif command == 'LIST':
			i.caps['LIST'] = l
			if 'LS' in i.caps:
				r = []
				# 'identify-msg' removed due to unability for default supybot's drivers to handles it correctly
				# ['account-notify','extended-join']
				# targeted caps
				CAPS = self.registryValue('caps')
				for cap in CAPS:
					if cap in i.caps['LS'] and not cap in i.caps['LIST']:
						r.append(cap)
				if len(r):
					# apply missed caps
					irc.queueMsg(ircmsgs.IrcMsg('CAP REQ :%s' % ' '.join(r)))
		elif command == 'ACK' or command == 'NAK':
			# retrieve current caps
			irc.queueMsg(ircmsgs.IrcMsg('CAP LIST'))
		self._tickle(irc)
	
	def doAccount (self,irc,msg):
		# update nick's model
		if ircutils.isUserHostmask(msg.prefix):
			nick = ircutils.nickFromHostmask(msg.prefix)
			n = self.getNick(irc,nick)
			old = n.account;
			acc = msg.args[0]
			if acc == '*':
				acc = None
			n.setAccount(acc)
			n.addLog('ALL','%s is now identified as %s' % (old,acc))
		self._tickle(irc)
	
	def doNotice (self,irc,msg):
		(targets, text) = msg.args
		if not ircutils.isUserHostmask(irc.prefix):
			return
		if targets == irc.nick:
			b = False
			if text == 'You are not authorized to perform this operation.':
				b = True
			if b:
				i = self.getIrc(irc)
				for nick in i.nicks:
					n = i.getNick(irc,nick)
					if n.prefix and ircdb.checkCapability(n.prefix, 'owner') and n.prefix != irc.prefix:
						irc.queueMsg(ircmsgs.privmsg(n.prefix.split('!')[0],'Warning got %s notice: %s' % (msg.prefix,text)))
						break
			#if text.startswith('*** Message to ') and text.endswith(' throttled due to flooding'):
				# as bot floods, todo schedule info to owner
		else:
			if msg.nick == irc.nick:
				return
			n = self.getNick(irc,msg.nick)
			patterns = getBestPattern(n)
			best = False
			if len(patterns):
				best = patterns[0]
			for channel in targets.split(','):
				if irc.isChannel(channel) and channel in irc.state.channels:
					chan = self.getChan(irc,channel)
					n.addLog(channel,'NOTICE | %s' % text)
					# why flood logChannel ..
					#self._logChan(irc,channel,'[%s] %s notices "%s"' % (channel,msg.prefix,text))
					# checking if message matchs living massRepeatPattern
					for pattern in chan.massPattern:
						if self._strcompare(pattern,text) >= self.registryValue('massRepeatPercent',channel=channel):
							kind = 'massRepeat'
							mode = self.registryValue('%sMode' % kind,channel=channel)
							duration = self.registryValue('%sDuration' % kind,channel=channel)
							comment = self.registryValue('%sComment' % kind,channel=channel)
							self._act(irc,channel,mode,best,duration,comment)
							self.forceTickle = True
							best = None
					if best:
						isNotice = self._isSomething(irc,channel,best,'notice')
						isMass = False
						if len(text) >= self.registryValue('massRepeatChars',channel=channel):
							isMass = self._isSomething(irc,channel,text,'massRepeat')
						if isNotice:
							isBad = self._isSomething(irc,channel,best,'bad')
							kind = None
							if isBad:
								kind = 'bad'
							elif isMass:
								kind = 'massRepeat'
								if not text in chan.massPattern:
									chan.massPattern[text] = text
									def unpattern ():
										if text in chan.massPattern:
											del chan.massPattern[text]
									# remove pattern after massRepeatDuration, maybe add another config value ?
									schedule.addEvent(unpattern,time.time()+self.registryValue('massRepeatDuration',channel=channel))
							else:
								kind = 'notice'
							mode = self.registryValue('%sMode' % kind,channel=channel)
							if len(mode) > 1:
								mode = mode[0]
							duration = self.registryValue('%sDuration' % kind,channel=channel)
							comment = self.registryValue('%sComment' % kind,channel=channel)
							self._act(irc,channel,mode,best,duration,comment)
							self.forceTickle = True
		self._tickle(irc)
	
	def doPrivmsg (self,irc,msg):
		if msg.nick == irc.nick:
			self._tickle(irc)
			return
		(recipients, text) = msg.args
		isAction = ircmsgs.isAction(msg)
		isCtcpMsg = ircmsgs.isCtcp(msg)
		if isAction:
			text = ircmsgs.unAction(msg)
		n = None
		best = None
		if ircutils.isUserHostmask(msg.prefix):
			n = self.getNick(irc,msg.nick)
			patterns = getBestPattern(n)
			if len(patterns):
				best = patterns[0]
			# if it fails here stacktrace
		if not n or not best:
			# server msgs or plugin reload, or state not ready
			self._tickle(irc)
			return
		for channel in recipients.split(','):
			if irc.isChannel(channel) and channel in irc.state.channels:
				chan = self.getChan(irc,channel)
				message = text
				if isCtcpMsg and not isAction:
					message = 'CTCP | %s' % text
					self._logChan(irc,channel,'[%s] %s ctcps "%s"' % (channel,msg.prefix,text))
				elif isAction:
					message = '- %s -' % text
				n.addLog(channel,message)
				# protection features
				
				# checking if message matchs living massRepeatPattern
				for pattern in chan.massPattern:
					if self._strcompare(pattern,text) >= self.registryValue('massRepeatPercent',channel=channel):
						kind = 'massRepeat'
						mode = self.registryValue('%sMode' % kind,channel=channel)
						duration = self.registryValue('%sDuration' % kind,channel=channel)
						comment = self.registryValue('%sComment' % kind,channel=channel)
						self._act(irc,channel,mode,best,duration,comment)
						self.forceTickle = True
						# no needs to check others protection
						continue
						
				isCtcp = False
				if isCtcpMsg:
					isCtcp = self._isSomething(irc,channel,best,'ctcp')
				isFlood = self._isFlood(irc,channel,best)
				isLowFlood = self._isLowFlood(irc,channel,best)
				isRepeat = self._isRepeat(irc,channel,best,text)
				isHilight = self._isHilight(irc,channel,best,text)
				isCap = self._isCap(irc,channel,best,text)
				isMass = False
				if len(text) >= self.registryValue('massRepeatChars',channel=channel):
					isMass = self._isSomething(irc,channel,text,'massRepeat')
				if isFlood or isHilight or isRepeat or isCap or isCtcp or isLowFlood or isMass:
					isBad = self._isBad(irc,channel,best)
					kind = None
					duration = 0
					if isBad:
						kind = 'bad'
						duration = self.registryValue('badDuration',channel=channel)
					else:
						# todo select the hardest duration / mode
						if isMass:
							kind = 'massRepeat'
							duration = self.registryValue('massRepeatDuration',channel=channel)
							if not text in chan.massPattern:
								chan.massPattern[text] = text
								def unpattern ():
									if text in chan.massPattern:
										del chan.massPattern[text]
								# remove pattern after massRepeatDuration, maybe add another config value ?
								schedule.addEvent(unpattern,time.time()+duration)
						if isFlood:
							d = self.registryValue('floodDuration',channel=channel)
							if d > duration:
								kind = 'flood'
								duration = d
						if isLowFlood:
							d = self.registryValue('lowFloodDuration',channel=channel)
							if d > duration:
								kind = 'lowFlood'
								duration = d
						if isRepeat:
							d = self.registryValue('repeatDuration',channel=channel)
							if d > duration:
								kind = 'repeat'
								duration = d
						if isHilight:
							d = self.registryValue('hilightDuration',channel=channel)
							if d > duration:
								kind = 'hilight'
								duration = d
						if isCap:
							d = self.registryValue('capDuration',channel=channel)
							if d > duration:
								kind = 'cap'
								duration = d
						if isCtcp:
							d = self.registryValue('ctcpDuration',channel=channel)
							if d > duration:
								kind = 'ctcp'
								duration = d
					mode = self.registryValue('%sMode' % kind,channel=channel)
					if len(mode) > 1:
						mode = mode[0]
					duration = self.registryValue('%sDuration' % kind,channel=channel)
					comment = self.registryValue('%sComment' % kind,channel=channel)
					self._act(irc,channel,mode,best,duration,comment)
					self.forceTickle = True
		self._tickle(irc)
	
	def doTopic(self, irc, msg):
		if len(msg.args) == 1:
			return
		if ircutils.isUserHostmask(msg.prefix):
			n = self.getNick(irc,msg.nick)
		channel = msg.args[0]
		if channel in irc.state.channels:
			if n:
				n.addLog(channel,'sets topic "%s"' % msg.args[1])
			self._logChan(irc,channel,'[%s] %s sets topic "%s"' % (channel,msg.prefix,msg.args[1]))
	
	def doMode(self, irc, msg):
		channel = msg.args[0]
		now = time.time()
		n = None
		i = self.getIrc(irc)
		if ircutils.isUserHostmask(msg.prefix):
			# prevent server.netsplit to create a Nick
			n = self.getNick(irc,msg.nick)
			n.setPrefix(msg.prefix)
		# umode otherwise
		if irc.isChannel(channel) and msg.args[1:] and channel in irc.state.channels:
			modes = ircutils.separateModes(msg.args[1:])
			chan = self.getChan(irc,channel)
			msgs = []
			overexpire = self.registryValue('autoExpire',channel=channel)
			for change in modes:
				(mode,value) = change
				if value:
					value = value.lstrip().rstrip()
					item = None
					if '+' in mode:
						m = mode[1:]
						if m in self.registryValue('modesToAskWhenOpped') or m in self.registryValue('modesToAsk'):
							item = chan.addItem(m,value,msg.prefix,now,self.getDb(irc.network))
							if overexpire > 0:
								# overwrite expires
								if msg.nick != irc.nick:
									# an op do something, and over expires is enabled, announce or not ? currently not. change last flag
									i.edit(irc,channel,m,value,overexpire,irc.prefix,self.getDb(irc.network),self._logChan,True)
									self.forceTickle = True
						# here bot could add others mode changes or actions
						if item and len(item.affects):
							for affected in item.affects:
								nick = affected.split('!')[0]
								kicked = False
								if m in self.registryValue('kickMode',channel=channel):
									if nick in irc.state.channels[channel].users:
										i.queue.enqueue(ircmsgs.kick(channel,nick,self.registryValue('kickMessage')))
										self.forceTickle = True
										kicked = True
								if not kicked and m in self.registryValue('modesToAsk'):
									acts = []
									if nick in irc.state.channels[channel].ops:
										acts.append(('-o',nick))
									if nick in irc.state.channels[channel].voices:
										acts.append(('-v',nick))
									if len(acts):
										irc.sendMsg(ircmsgs.IrcMsg(prefix=irc.prefix, command='MODE',args=[channel] + ircutils.joinModes(acts)))
										self.forceTickle = True
						# bot just got op
						if m == 'o' and value == irc.nick:
							chan.opAsked = False
							ms = ''
							asked = self.registryValue('modesToAskWhenOpped')
							for k in asked:
								if not k in chan.dones:
									ms = ms + k
							if len(ms):
								# update missed list, using sendMsg, as the bot may ask for -o just after
								irc.sendMsg(ircmsgs.IrcMsg('MODE %s %s' % (channel,ms)))
							# flush pending queue, if items are waiting
							self.forceTickle = True
					else:
						m = mode[1:]
						if m == 'o' and value == irc.nick:
							# prevent bot to sent many -o modes when server takes time to reply
							chan.deopAsked = False
						if m in self.registryValue('modesToAskWhenOpped') or m in self.registryValue('modesToAsk'):
							item = chan.removeItem(m,value,msg.prefix,self.getDb(irc.network))
					if n:
						n.addLog(channel,'sets %s %s' % (mode,value))
					if item:
						if '+' in mode:
							if len(item.affects) != 1:
								msgs.append('[#%s %s %s - %s users]' % (item.uid,mode,value,len(item.affects)))
							else:
								msgs.append('[#%s %s %s - %s]' % (item.uid,mode,value,item.affects[0]))
						else:
							if len(item.affects) != 1:
								# something odds appears during tests, when channel is not sync, and there is some removal, item.remove_at or item.when aren't Float
								# TODO check before string format maybe
								# left as it is, trying to reproduce
								msgs.append('[#%s %s %s - %s users, %s]' % (item.uid,mode,value,len(item.affects),utils.timeElapsed(item.removed_at-item.when)))
							else:
								msgs.append('[#%s %s %s - %s, %s]' % (item.uid,mode,value,item.affects[0],utils.timeElapsed(item.removed_at-item.when)))
					else:
						msgs.append('[%s %s]' % (mode,value))
				else:
					if n:
						n.addLog(channel,'sets %s' % mode)
					msgs.append(mode)
			if irc.nick in irc.state.channels[channel].ops and not self.registryValue('keepOp',channel=channel):
				self.forceTickle = True
			self._logChan(irc,channel,'[%s] %s sets %s' % (channel,msg.prefix,' '.join(msgs)))
			self._tickle(irc)	
	
	def do478(self,irc,msg):
		# message when ban list is full after adding something to eqIb list
		(nick,channel,ban,info) = msg.args
		if info == 'Channel ban list is full':
			self._logChan(irc,channel,'[%s] %s' % (channel,info.upper()))
		self._tickle(irc)
	
	 # protection features
	
	def _act (self,irc,channel,mode,mask,duration,reason):
		if mode in self.registryValue('modesToAsk') or mode in self.registryValue('modesToAskWhenOpped'):
			i = self.getIrc(irc)
			if i.add(irc,channel,mode,mask,duration,irc.prefix,self.getDb(irc.network),self._logChan,True):
				if reason and len(reason):
					i.submark(irc,channel,mode,mask,reason,irc.prefix,self.getDb(irc.network),self._logChan)
			self.forceTickle = True
			self._tickle(irc)
		else:
			log.error('%s %s %s %s %s unsupported mode' % (channel,mode,mask,duration,reason))
	
	def _isSomething (self,irc,channel,key,prop):
		limit = self.registryValue('%sPermit' % prop,channel=channel)
		if limit == -1:
			return False
		chan = self.getChan(irc,channel)
		life = self.registryValue('%sLife' % prop,channel=channel)
		if not prop in chan.spam or chan.spam[prop].timeout != life:
			# reset queue if config has changed
			chan.spam[prop] = SpamQueue(life)
		chan.spam[prop].enqueue(key)
		if chan.spam[prop].len(key) > limit:
			chan.spam[prop].reset(key)
			return True
		return False
	
	def _isBad (self,irc,channel,key):
		return self._isSomething(irc,channel,key,'bad')
	
	def _isFlood(self,irc,channel,key):
		return self._isSomething(irc,channel,key,'flood')
	
	def _isLowFlood(self,irc,channel,key):
		return self._isSomething(irc,channel,key,'lowFlood')
	
	def _isHilight (self,irc,channel,key,message):
		limit = self.registryValue('hilightPermit',channel=channel)
		if limit == -1:
			return False
		count = 0
		for user in irc.state.channels[channel].users:
			count = count + message.count(user)
		return count > limit
	
	def _isRepeat(self,irc,channel,key,message):
		limit = self.registryValue('repeatPermit',channel=channel)	
		if limit == -1:
			return False
		chan = self.getChan(irc,channel)
		## needed to compare with previous text
		if not key in chan.repeatLogs:
			chan.repeatLogs[key] = utils.structures.MaxLengthQueue(limit*2)
		logs = chan.repeatLogs[key]
		if limit*2 != logs.length:
			logs = chan.repeatLogs[key] = utils.structures.MaxLengthQueue(limit*2)
		trigger = self.registryValue('repeatPercent',channel=channel)
		result = False
		if len(logs) > 0:
			flag = False
			for entry in logs:
				if self._strcompare(message,entry) >= trigger:
					flag = True
					break
			if flag:
				result = self._isSomething(irc,channel,key,'repeat')
		logs.enqueue(message)
		return result
	
	def _isCap(self,irc,channel,key,message):
		limit = self.registryValue('capPermit',channel=channel)
		if limit == -1:
			return False
		trigger = self.registryValue('capPercent',channel=channel)
		matchs = self.recaps.findall(message)
		percent = len(matchs) / len(message)
		if percent >= trigger:
			return self._isSomething(irc,channel,key,'cap')
		return False
	
	def _strcompare (self,a,b):
		# return [0 - 1] ratio between two string
		# jaccard algo
		c = [x for x in a if x in b]
		return float(len(c)) / (len(a) + len(b) - len(c))


Class = ChanTracker


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
