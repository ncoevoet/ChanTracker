###
# Copyright (c) 2013, Nicolas Coevoet
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
import socket
import re
import sqlite3
import collections

#due to more kind of pattern checked, increase size

ircutils._hostmaskPatternEqualCache = utils.structures.CacheDict(4000)

cache = utils.structures.CacheDict(4000)

def matchHostmask (pattern,n):
	# return the machted pattern for Nick
	if n.prefix == None or not ircutils.isUserHostmask(n.prefix):
		return None
	(nick,ident,host) = ircutils.splitHostmask(n.prefix)
	if host.find('/') != -1:
		# cloaks
		if host.startswith('gateway/web/freenode/ip.'):
			n.ip = cache[host] = host.split('ip.')[1]
	else:
		# trying to get ip
		if host in cache:
			n.ip = cache[host]
		else:
			n.setIp(host)
			if n.ip != None:
				cache[host] = n.ip
			else:
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
							cache[host] = L[0]
							n.setIp(L[0])
						else:
							cache[host] = None
				except:
					cache[host] = None
	if n.ip != None and ircutils.hostmaskPatternEqual(pattern,'%s!%s@%s' % (nick,ident,n.ip)):
		return '%s!%s@%s' % (nick,ident,n.ip)
	if ircutils.hostmaskPatternEqual(pattern,n.prefix):
		return n.prefix
	return None
	
def matchAccount (pattern,pat,negate,n,extprefix):
	# for $a, $~a, $a: extended pattern
	result = None
	if negate:
		if not len(pat) and n.account == None:
			result = n.prefix
	else:
		if len(pat):
			if n.account != None and ircutils.hostmaskPatternEqual('*!*@%s' % pat, '*!*@%s' % n.account):
				result = '%sa:%s' % (extprefix,n.account)
		else:
			if n.account != None:
				result = '%sa:%s' % (extprefix,n.account)
	return result

def matchRealname (pattern,pat,negate,n,extprefix):
	# for $~r $r: extended pattern
	if n.realname == None:
		return None
	if negate:
		if len(pat):
			if not ircutils.hostmaskPatternEqual('*!*@%s' % pat, '*!*@%s' % n.realname):
				return '%sr:%s' % (extprefix,n.realname.replace(' ','?'))
	else:
		if len(pat):
			if ircutils.hostmaskPatternEqual('*!*@%s' % pat, '*!*@%s' % n.realname):
				return '%sr:%s' % (extprefix,n.realname.replace(' ','?'))
	return None

def matchGecos (pattern,pat,negate,n,extprefix):
	# for $~x, $x: extended pattern
	if n.realname == None:
		return None
	tests = []
	(nick,ident,host) = ircutils.splitHostmask(n.prefix)
	tests.append(n.prefix)
	if n.ip != None:
		tests.append('%s!%s@%s' % (nick,ident,n.ip))
	for test in tests:
		test = '%s#%s' % (test,n.realname.replace(' ','?'))
		if negate:
			if not ircutils.hostmaskPatternEqual(pat,test):
				return test
		else:
			if ircutils.hostmaskPatternEqual(pat,test):
				return test
	return None

def match (pattern,n,irc):
	if not pattern:
		return None
	if not n.prefix:
		return None
	# check if given pattern match an Nick
	key = pattern + ' :: ' + str(n)
	if key in cache:
		return cache[key]
	cache[key] = None
	extprefix = ''
	extmodes = ''
	if 'extban' in irc.state.supported:
		ext = irc.state.supported['extban']
		extprefix = ext.split(',')[0]
		extmodes = ext.split(',')[1]
	if pattern.startswith(extprefix):
		p = pattern[1:]
		negate = extmodes.find(p[0]) == -1
		if negate:
			p = p[1:]
		t = p[0]
		p = p[1:]
		if len(p):
			# remove ':'
			p = p[1:]
		if p.find('$') != -1:
			# forward
			p = p[(p.rfind('$')+1):]
		if t == 'a':
			cache[key] = matchAccount (pattern,p,negate,n,extprefix)
		elif t == 'r':
			cache[key] = matchRealname (pattern,p,negate,n,extprefix)
		elif t == 'x':
			cache[key] = matchGecos (pattern,p,negate,n,extprefix)
		else:
			# bug if ipv6 used ..
			k = pattern[(pattern.rfind(':')+1):]
			cache[key] = matchHostmask(k,n)
	else:
		p = pattern
		if p.find(extprefix) != -1:
			p = p.split(extprefix)[0]
		if ircutils.isUserHostmask(p):
			cache[key] = matchHostmask(p,n)
		else:
			log.error('%s pattern is not supported' % pattern)
	return cache[key]

def getBestPattern (n,irc):
	# return best pattern for a given Nick
	match(n.prefix,n,irc)
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
		if len(n.ip.split(':')) > 4:
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
	k = '*!%s@%s' % (ident,host)
	if not k in results:
		results.append(k)
	extprefix = ''
	extmodes = ''
	if 'extban' in irc.state.supported:
		ext = irc.state.supported['extban']
		extprefix = ext.split(',')[0]
		extmodes = ext.split(',')[1]
	if n.account:
		results.append('%sa:%s' % (extprefix,n.account))
	if n.realname:
		results.append('%sr:%s' % (extprefix,n.realname.replace(' ','?')))
	return results

def clearExtendedBanPattern (pattern,irc):
	# a little method to cleanup extended pattern
	extprefix = ''
	extmodes = ''
	if 'extban' in irc.state.supported:
		ext = irc.state.supported['extban']
		extprefix = ext.split(',')[0]
		extmodes = ext.split(',')[1]
	if pattern.startswith(extprefix):
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

class Ircd (object):
	# define an ircd, keeps Chan and Nick items
	def __init__(self,irc,logsSize):
		object.__init__(self)
		self.irc = irc
		self.name = irc.network
		self.channels = ircutils.IrcDict()
		self.nicks = ircutils.IrcDict()
		self.caps = ircutils.IrcDict()
		# contains IrcMsg, kicks, modes, etc
		self.queue = utils.structures.smallqueue()
		# contains less important IrcMsgs ( sync, logChannel )
		self.lowQueue = utils.structures.smallqueue()
		self.logsSize = logsSize
		self.askedItems = {}		

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
	
	def getItem (self,irc,uid):
		# return active item
		if not irc or not uid:
			return None
		for channel in list(self.channels.keys()):
			chan = self.getChan(irc,channel)
			items = chan.getItems()
			for type in list(items.keys()):
				for value in items[type]:
					item = items[type][value]
					if item.uid == uid:
						return item
		# TODO maybe uid under modes that needs op to be shown ?
		return None

	def info (self,irc,uid,prefix,db):
		# return mode changes summary
		if not uid or not prefix:
			return []
		c = db.cursor()
		c.execute("""SELECT channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE id=? LIMIT 1""",(uid,))
		L = c.fetchall()
		if not len(L):
			c.close()
			return []
		(channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by) = L[0]
		if not ircdb.checkCapability(prefix, '%s,op' % channel):
			c.close()
			return []
		results = []
		current = time.time()
		results.append('[%s] [%s] %s sets +%s %s' % (channel,floatToGMT(begin_at),oper,kind,mask))
		if not removed_at:
			if begin_at == end_at:
				results.append('set forever')
			else:
				s = 'set for %s' % utils.timeElapsed(end_at-begin_at)
				s = s + ' with %s more' % utils.timeElapsed(end_at-current)
				s = s + ' and ends at [%s]' % floatToGMT(end_at)
				results.append(s)
		else:
			s = 'was active %s and ended on [%s]' % (utils.timeElapsed(removed_at-begin_at),floatToGMT(removed_at))
			if end_at != begin_at:
				s = s + ' ,initialy for %s' % utils.timeElapsed(end_at-begin_at)
			results.append(s)
		c.execute("""SELECT oper, comment FROM comments WHERE ban_id=? ORDER BY at DESC""",(uid,))
		L = c.fetchall()
		if len(L):
			for com in L:
				(oper,comment) = com
				results.append('"%s" by %s' % (comment,oper))
		c.execute("""SELECT full,log FROM nicks WHERE ban_id=?""",(uid,))
		L = c.fetchall()
		if len(L) == 1:
			for affected in L:
				(full,log) = affected
				message = ""
				for line in log.split('\n'):
					message = '%s' % line
					break
				results.append(message)
		elif len(L) > 1:
			results.append('affects %s users' % len(L))
		#if len(L):
			#for affected in L:
				#(full,log) = affected
				#message = full
				#for line in log.split('\n'):
					#message = '[%s]' % line
					#break
				#results.append(message)
		c.close()
		return results
	
	def pending(self,irc,channel,mode,prefix,pattern,db,notExpiredOnly=False):
		# returns active items for a channel mode
		if not channel or not mode or not prefix:
			return []
		if not ircdb.checkCapability(prefix, '%s,op' % channel):
			return []
		chan = self.getChan(irc,channel)
		results = []
		r = []
		c = db.cursor()
		for m in mode:
			items = chan.getItemsFor(m)
			if len(items):
				for item in items:
					item = items[item]
					if notExpiredOnly:
						if item.when == item.expire or not item.expire:
							r.append([item.uid,item.mode,item.value,item.by,item.when,item.expire])
					else:
						r.append([item.uid,item.mode,item.value,item.by,item.when,item.expire])
		r.sort(reverse=True)
		if len(r):
			for item in r:
				(uid,mode,value,by,when,expire) = item
				if pattern != None and not ircutils.hostmaskPatternEqual(pattern,by):
					continue
				c.execute("""SELECT oper, comment FROM comments WHERE ban_id=? ORDER BY at DESC LIMIT 1""",(uid,))
				L = c.fetchall()
				if len(L):
					(oper,comment) = L[0]
					message = ' "%s"' % comment
				else: 
					message = ''
				if expire and expire != when:
					results.append('[#%s +%s %s by %s expires at %s]%s' % (uid,mode,value,by,floatToGMT(expire),message))
				else:
					results.append('[#%s +%s %s by %s on %s]%s' % (uid,mode,value,by,floatToGMT(when),message))	
		c.close()
		return results
	
	def against (self,irc,channel,n,prefix,db):
		# returns active items which matchs n
		if not channel or not n or not db:
			return []
		if not ircdb.checkCapability(prefix, '%s,op' % channel):
			return []
		chan = self.getChan(irc,channel)
		results = []
		r = []
		c = db.cursor()
		for k in list(chan.getItems()):
			items = chan.getItemsFor(k)
			if len(items):
				for item in items:
					item = items[item]
					if match(item.value,n,irc):
						r.append([item.uid,item.mode,item.value,item.by,item.when,item.expire])
		r.sort(reverse=True)
		if len(r):
			for item in r:
				(uid,mode,value,by,when,expire) = item
				c.execute("""SELECT oper, comment FROM comments WHERE ban_id=? ORDER BY at DESC LIMIT 1""",(uid,))
				L = c.fetchall()
				if len(L):
					(oper,comment) = L[0]
					message = ' "%s"' % comment
				else: 
					message = ''
				if expire and expire != when:
					results.append('[#%s +%s %s by %s expires at %s]%s' % (uid,mode,value,by,floatToGMT(expire),message))
				else:
					results.append('[#%s +%s %s by %s on %s]%s' % (uid,mode,value,by,floatToGMT(when),message))	
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
			c.close()
			return []
		results = []
		#c.execute("""SELECT oper, comment, at FROM comments WHERE ban_id=? ORDER BY at DESC""",(uid,))
		#L = c.fetchall()
		#if len(L):
			#for com in L:
				#(oper,comment,at) = com
				#results.append('"%s" by %s on %s' % (comment,oper,floatToGMT(at)))
		c.execute("""SELECT full,log FROM nicks WHERE ban_id=?""",(uid,))
		L = c.fetchall()
		if len(L):
			for item in L:
				(full,log) = item
				results.append('For [%s]' % full)
				for line in log.split('\n'):
					results.append(line)
		else:
			results.append('no log found')
		c.close()
		return results
	
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
			pattern = clearExtendedBanPattern(pattern,irc)
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
		c.execute("""SELECT ban_id, full FROM nicks WHERE full GLOB ? OR full LIKE ? OR log GLOB ? OR log LIKE ? ORDER BY ban_id DESC""",(glob,like,glob,like))
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
					if isOwner or ircdb.checkCapability(prefix, '%s,op' % channel):
						results.append([uid,mask,kind,channel])
		if len(results):
			results.sort(reverse=True)
			i = 0
			msgs = []
			while i < len(results):
				(uid,mask,kind,channel) = results[i]
				msgs.append('[#%s +%s %s in %s]' % (uid,kind,mask,channel))
				i = i+1
			return msgs
		return []
	
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
			c.close()
			return []
		results = []
		c.execute("""SELECT full,log FROM nicks WHERE ban_id=?""",(uid,))
		L = c.fetchall()
		if len(L):
			for item in L:
				(full,log) = item
				message = full
				for line in log.split('\n'):
					message = '[%s]' % line
					break
				results.append(message)
		else:
			results.append('nobody affected')
		c.close()
		return results
	
	def markremoved (self,irc,uid,message,prefix,db,ct):
		# won't use channel,mode,value, because Item may be removed already
		# it's a duplicate of mark, only used to compute logChannel on a removed item
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
			f = None
			if prefix != irc.prefix and ct.registryValue('announceEdit',channel=channel):
				f = ct._logChan
			elif prefix == irc.prefix and ct.registryValue('announceBotMark',channel=channel):
				f = ct._logChan
			if f:
				f(irc,channel,'[%s] [#%s +%s %s] marked by %s: %s' % (channel,uid,kind,mask,prefix.split('!')[0],message))
			b = True
		c.close()
		return b
	
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
			if logFunction:
				logFunction(irc,channel,'[%s] [#%s +%s %s] marked by %s: %s' % (channel,uid,kind,mask,prefix.split('!')[0],message))
			b = True
		c.close()
		return b
	
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
			# item exists
			(uid,oper) = L[0]
			c.close()
			# must not be occurs, but ..
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
	
	def add (self,irc,channel,mode,value,seconds,prefix,db):
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
			c.close()
			# TODO maybe edit item here ?
			return False
		else:
			if channel in self.channels:
				chan = self.getChan(irc,channel)
				item = chan.getItem(mode,value)
				hash = '%s%s' % (mode,value)
				# prepare item update after being set ( we don't have id yet )
				chan.update[hash] = [mode,value,seconds,prefix]
				# enqueue mode changes
				chan.queue.enqueue(('+%s' % mode,value))
				return True
		return False
	
	def edit (self,irc,channel,mode,value,seconds,prefix,db,scheduleFunction,logFunction):
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
			current = float(time.time())
			if begin_at == end_at:
				text = 'was forever'
			else:
				text = 'ended [%s] for %s' % (floatToGMT(end_at),utils.timeElapsed(end_at-begin_at))
			if seconds < 0:
				newEnd = begin_at
				reason = 'never expires'
			elif seconds == 0:
				newEnd = current # force expires for next tickle
				reason = 'expires at [%s], for %s in total' % (floatToGMT(newEnd),utils.timeElapsed(newEnd-begin_at))
			else:
				newEnd = current+seconds
				reason = 'expires at [%s], for %s in total' % (floatToGMT(newEnd),utils.timeElapsed(newEnd-begin_at))
			text = '%s, now %s' % (text,reason)
			c.execute("""INSERT INTO comments VALUES (?, ?, ?, ?)""",(uid,prefix,current,text))
			c.execute("""UPDATE bans SET end_at=? WHERE id=?""", (newEnd,int(uid)))
			db.commit()
			i = chan.getItem(kind,mask)
			if i:
				if newEnd == begin_at:
					i.expire = None
				else:
					i.expire = newEnd
					if scheduleFunction and newEnd != current:
						scheduleFunction(irc,newEnd)
			if logFunction:
				logFunction(irc,channel,'[%s] [#%s +%s %s] edited by %s: %s' % (channel,uid,kind,mask,prefix.split('!')[0],reason))
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
			if logFunction:
				logFunction(irc,channel,'[%s] [%s] %s removed: %s' % (channel,mode,commits, ' '.join(msgs)))
		c.close()

class Chan (object):
	# in memory and in database stores +eIqb list -ov
	# no user action from here, only ircd messages
	def __init__(self,ircd,name):
		object.__init__(self)
		self.ircd = ircd
		self.name = name
		self._lists = ircutils.IrcDict()
		# queue contains (mode,valueOrNone) - ircutils.joinModes
		self.queue = utils.structures.smallqueue()
		# contains [modevalue] = [mode,value,seconds,prefix]
		self.update = ircutils.IrcDict()
		# contains [modevalue] = [mode,value,message,prefix]
		self.mark = ircutils.IrcDict()
		# contains IrcMsg ( mostly kick / fpart )
		self.action = utils.structures.smallqueue()
		# looking for eqIb list ends
		self.dones = []
		self.syn = False
		self.opAsked = False
		self.deopAsked = False
		self.deopPending = False
		# now stuff here is related to protection
		self.spam = ircutils.IrcDict()
		self.repeatLogs = ircutils.IrcDict()
		self.nicks = ircutils.IrcDict()
	
	def isWrong (self,pattern):
		if 'bad' in self.spam and pattern in self.spam['bad']:
			if len(self.spam['bad'][pattern]) > 0:
				return True
		return False
		
	def getItems (self):
		# [X][Item.value] is Item
		return self._lists
	
	def getItemsFor (self,mode):
		if not mode in self._lists:
			self._lists[mode] = ircutils.IrcDict()
		return self._lists[mode]

	def addItem (self,mode,value,by,when,db,checkUser=True):
		# eqIb(+*) (-ov) pattern prefix when 
		# mode : eqIb -ov + ?
		l = self.getItemsFor(mode)
		if not value in l:
			i = Item()
			i.channel = self.name
			i.mode = mode
			i.value = value
			uid = None
			expire = when
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
				uid = c.lastrowid
				# leave channel's users list management to supybot
				ns = []
				if self.name in self.ircd.irc.state.channels and checkUser:
					L = []
					for nick in list(self.ircd.irc.state.channels[self.name].users):
						L.append(nick)
					for nick in L:
						n = self.ircd.getNick(self.ircd.irc,nick)
						m = match(value,n,self.ircd.irc)
						if m:
							i.affects.append(n.prefix)
							# insert logs
							index = 0
							logs = []
							logs.append('%s' % n)
							for line in n.logs:
								(ts,target,message) = n.logs[index]
								index += 1
								if target == self.name or target == 'ALL':
									logs.append('[%s] <%s> %s' % (floatToGMT(ts),nick,message))
							c.execute("""INSERT INTO nicks VALUES (?, ?, ?, ?)""",(uid,value,n.prefix,'\n'.join(logs)))
							ns.append([n,m])
				db.commit()
			c.close()
			i.uid = uid
			i.by = by
			i.when = float(when)
			i.expire = float(expire)
			l[value] = i
		return l[value]
		
	def getItem (self,mode,value):
		if mode in self._lists:
			if value in self._lists[mode]:
				return self._lists[mode][value]
		return None
		
	def removeItem (self,mode,value,by,c):
		# flag item as removed in database, we use a cursor as argument because otherwise database tends to be locked
		removed_at = float(time.time())
		i = self.getItem(mode,value)
		created = False
		if not i:
			c.execute("""SELECT id,oper,begin_at,end_at FROM bans WHERE channel=? AND kind=? AND mask=? AND removed_at is NULL ORDER BY id LIMIT 1""",(self.name,mode,value))
			L = c.fetchall()
			if len(L):
				(uid,by,when,expire) = L[0]
				i = Item()
				i.uid = uid
				i.mode = mode
				i.value = value
				i.channel = self.named
				i.by = oper
				i.when = float(when)
				i.expire = float(expire)
		if i:
			c.execute("""UPDATE bans SET removed_at=?, removed_by=? WHERE id=?""", (removed_at,by,int(i.uid)))
			i.removed_by = by
			i.removed_at = removed_at
			self._lists[mode].pop(value)
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
		return 'Item(%s [%s][%s] by %s on %s, expire on %s, removed on %s by %s)' % (self.uid,self.mode,self.value,self.by,floatToGMT(self.when),floatToGMT(end),floatToGMT(self.removed_at),self.removed_by)
	
class Nick (object):
	def __init__(self,logSize):
		object.__init__(self)
		self.prefix = None
		self.ip = None
		self.realname = None
		self.account = None
		self.logSize = logSize
		self.logs = []
		# log format :
		# target can be a channel, or 'ALL' when it's related to nick itself ( account changes, nick changes, host changes, etc )
		# [float(timestamp),target,message]
	
	def setPrefix (self,prefix):
		if prefix != None and not prefix == self.prefix:
			self.prefix = prefix
		return self
	
	def setIp (self,ip):
		if not ip == self.ip and not ip == '255.255.255.255' and utils.net.isIP(ip):
			self.ip = ip
		return self
	
	def setAccount (self,account):
		if account == '*':
			account = None
		self.account = account
		return self
		
	def setRealname (self,realname):
		self.realname = realname
		return self
		
	def addLog (self,target,message):
		if len(self.logs) == self.logSize:
			self.logs.pop(0)
		self.logs.append([time.time(),target,message])
		return self
	
	def __repr__(self):
		ip = self.ip
		if ip is None:
			ip = ''
		account = self.account
		if account is None:
			account = ''
		realname = self.realname
		if realname is None:
			realname = ''
		return '%s ip:%s account:%s username:%s' % (self.prefix,ip,account,realname)

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
	items = list(args)
	for arg in items:
		if not arg or arg[-1] not in 'ywdhms':
			try:
				n = int(arg)
				state.args.append(n)
			except:
				state.args.append(float(seconds))
				raise callbacks.ArgumentError
		(s, kind) = arg[:-1], arg[-1]
		try:
			i = int(s)
		except ValueError:
			state.args.append(float(seconds))
			raise callbacks.ArgumentError
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
			if i == 0:
				i = 1
			seconds += i
		args.pop(0)
	state.args.append(float(seconds))

addConverter('getTs', getTs)

import threading
import supybot.world as world

def getDuration (seconds):
	if not len(seconds):
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
		self._ircs = ircutils.IrcDict()
		self.getIrc(irc)
		self.recaps = re.compile("[A-Z]")


	def editandmark (self,irc,msg,args,user,ids,seconds,reason):
		"""<id>[,<id>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1> or empty means forever, <0s> means remove] <reason>

		change expiration and mark an active mode change"""
		i = self.getIrc(irc)
		b = True
		for id in ids:
			be = False
			bm = False
			item = i.getItem(irc,id)
			if item:
				f = None
				if self.registryValue('announceEdit',channel=item.channel):
					f = self._logChan
				if getDuration(seconds) == 0 and not self.registryValue('announceInTimeEditAndMark',channel=item.channel):
					f = None
				be = i.edit(irc,item.channel,item.mode,item.value,getDuration(seconds),msg.prefix,self.getDb(irc.network),self._schedule,f)
				f = None
				if self.registryValue('announceMark',channel=item.channel):
					f = self._logChan
				if be:
					if reason and len(reason):
						bm = i.mark(irc,id,reason,msg.prefix,self.getDb(irc.network),f)
					else:
						bm = True
				b = b and be and bm
			else:
				b = False
		if b:
			irc.replySuccess()
		else:
			irc.reply('item not found, already removed or not enough rights to modify it')		
	editandmark = wrap(editandmark,['user',commalist('int'),any('getTs',True),rest('text')])
	
	def edit (self,irc,msg,args,user,ids,seconds):
		"""<id> [,<id>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1>] means forever

		change expiration of some active modes"""
		i = self.getIrc(irc)
		b = True
		for id in ids:
			item = i.getItem(irc,id)
			if item:
				f = None
				if msg.prefix != irc.prefix and self.registryValue('announceEdit',channel=item.channel):
					f = self._logChan
				elif msg.prefix == irc.prefix and self.registryValue('announceBotEdit',channel=item.channel):
					f = self._logChan
				if getDuration(seconds) == 0 and not self.registryValue('announceInTimeEditAndMark',channel=item.channel):
					f = None
				b = b and i.edit(irc,item.channel,item.mode,item.value,getDuration(seconds),msg.prefix,self.getDb(irc.network),self._schedule,f)
			else:
				b = False;
		if not msg.nick == irc.nick:
			if b:
				irc.replySuccess()
			else:
				irc.reply('item not found, already removed or not enough rights to modify it')
		self.forceTickle = True
		self._tickle(irc)
	edit = wrap(edit,['user',commalist('int'),any('getTs')])
	
	def info (self,irc,msg,args,user,id):
		"""<id>

		summary of a mode change"""
		i = self.getIrc(irc)
		results = i.info(irc,id,msg.prefix,self.getDb(irc.network))
		if len(results):
			for message in results:
				irc.queueMsg(ircmsgs.privmsg(msg.nick,message))
			#irc.replies(results,None,None,False,None,True)
		else:
			irc.reply('item not found or not enough rights to see information')
		self._tickle(irc)
	info = wrap(info,['user','int'])
	
	def detail (self,irc,msg,args,user,uid):
		"""<id>

		logs of a mode change"""
		i = self.getIrc(irc)
		results = i.log (irc,uid,msg.prefix,self.getDb(irc.network))
		if len(results):
			irc.replies(results,None,None,False,None,True)
		else:
			irc.reply('item not found or not enough rights to see detail')
		self._tickle(irc)
	detail = wrap(detail,['private','user','int'])
	
	def affect (self,irc,msg,args,user,uid):
		"""<id>

		list users affected by a mode change"""
		i = self.getIrc(irc)
		results = i.affect (irc,uid,msg.prefix,self.getDb(irc.network))
		if len(results):
			irc.replies(results,None,None,False,None,True)
		else:
			irc.reply('item not found or not enough rights to see affected users')
		self._tickle(irc)
	affect = wrap(affect, ['private','user','int'])
	
	def mark(self,irc,msg,args,user,ids,message):
		"""<id> [,<id>] <message>

		add comment on a mode change"""
		i = self.getIrc(irc)
		b = True
		for id in ids:
			item = i.getItem(irc,id)
			if item:
				f = None
				if msg.prefix != irc.prefix and self.registryValue('announceEdit',channel=item.channel):
					f = self._logChan
				elif msg.prefix == irc.prefix and self.registryValue('announceBotMark',channel=item.channel):
					f = self._logChan
				b = b and i.mark(irc,id,message,msg.prefix,self.getDb(irc.network),f)
			else:
				b = b and i.markremoved(irc,id,message,msg.prefix,self.getDb(irc.network),self)
		if not msg.nick == irc.nick:
			if b:
				irc.replySuccess()
			else:
				irc.reply('item not found or not enough rights to mark it')
		self.forceTickle = True
		self._tickle(irc)
	mark = wrap(mark,['user',commalist('int'),'text'])
	
	def query (self,irc,msg,args,user,text):
		"""<pattern|hostmask>

		returns known mode changes with deep search, channel's ops can only see items for their channels"""
		i = self.getIrc(irc)
		results = i.search(irc,text,msg.prefix,self.getDb(irc.network))
		if len(results):
			irc.replies(results,None,None,False,None,True)
		else:
			irc.reply('nothing found')
	query = wrap(query,['private','user','text'])
	
	def pending (self, irc, msg, args, channel, mode, pattern, notExpired):
		"""[<channel>] [<mode>] [<nick|hostmask>] [<onlyNotExpired>]

		returns active items for mode if given otherwise all modes are returned, if hostmask given, filtered by oper"""
		i = self.getIrc(irc)
		if pattern in i.nicks:
			pattern = self.getNick(pattern).prefix
		results = []
		if not mode:
			modes = self.registryValue('modesToAskWhenOpped',channel=channel) + self.registryValue('modesToAsk',channel=channel)
			results = i.pending(irc,channel,modes,msg.prefix,pattern,self.getDb(irc.network),False)
		else:
			results = i.pending(irc,channel,mode,msg.prefix,pattern,self.getDb(irc.network),notExpired)
		if len(results):
			irc.reply(' '.join(results), private=True)
		else:
			irc.reply('no results')
	pending = wrap(pending,['op',additional('letter'),optional('hostmask'),optional('boolean')])
	
	def _modes (self,numModes,chan,modes,f):
		for i in range(0, len(modes), numModes):
			chan.action.enqueue(f(modes[i:i + numModes]))
	
	def modes (self, irc, msg, args, channel, modes):
		"""[<channel>] <mode> [<arg> ...]

		Sets the mode in <channel> to <mode>, sending the arguments given.
		<channel> is only necessary if the message isn't sent in the channel
		itself. it bypass autoexpire and everything, bot will ask for OP, if needed.
		"""
		def f(L):
			return ircmsgs.modes(channel,L)
		self._modes(irc.state.supported.get('modes', 1),self.getChan(irc,channel),ircutils.separateModes(modes),f)
		self.forceTickle = True
		self._tickle(irc)
	modes = wrap(modes, ['op', many('something')])

	def do (self,irc,msg,args,channel,mode,items,seconds,reason):
		"""[<channel>] <mode> <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1> or empty means forever] <reason>

		+<mode> targets for duration <reason> is mandatory"""
		if mode in self.registryValue('modesToAsk',channel=channel) or mode in self.registryValue('modesToAskWhenOpped',channel=channel):
			b = self._adds(irc,msg,args,channel,mode,items,getDuration(seconds),reason)
			if not msg.nick == irc.nick and not b:
				irc.reply('unknown pattern or pattern already active')
		else:
			irc.reply('selected mode is not supported by config')
			
	do = wrap(do,['op','letter',commalist('something'),any('getTs',True),rest('text')])
	
	def q (self,irc,msg,args,channel,items,seconds,reason):
		"""[<channel>] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1> or empty means forever] <reason>

		+q targets for duration <reason> is mandatory"""
		b = self._adds(irc,msg,args,channel,'q',items,getDuration(seconds),reason)
		if not msg.nick == irc.nick and not b:
			irc.reply('unknown pattern, or pattern already active')
	q = wrap(q,['op',commalist('something'),any('getTs',True),rest('text')])
	
	def b (self, irc, msg, args, channel, items, seconds, reason):
		"""[<channel>] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1> or empty means forever] <reason>

		+b targets for duration <reason> is mandatory"""
		b = self._adds(irc,msg,args,channel,'b',items,getDuration(seconds),reason)
		if not msg.nick == irc.nick and not b:
			irc.reply('unknown pattern, or pattern already active')
	b = wrap(b,['op',commalist('something'),any('getTs',True),rest('text')])
	
	def i (self, irc, msg, args, channel, items, seconds, reason):
		"""[<channel>] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1> or empty means forever] <reason>

		+I targets for duration <reason> is mandatory"""
		b = self._adds(irc,msg,args,channel,'I',items,getDuration(seconds),reason)
		if not msg.nick == irc.nick and not b:
			irc.reply('unknown pattern, or pattern already active')
	i = wrap(i,['op',commalist('something'),any('getTs',True),rest('text')])
	
	def e (self, irc, msg, args, channel, items, seconds, reason):
		"""[<channel>] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1> or empty means forever] <reason>

		+e targets for duration <reason> is mandatory"""
		b = self._adds(irc,msg,args,channel,'e',items,getDuration(seconds),reason)
		if not msg.nick == irc.nick and not b:
			irc.reply('unknown pattern, or pattern already active')
	e = wrap(e,['op',commalist('something'),any('getTs'),rest('text')])
	
	def undo (self, irc, msg, args, channel, mode, items):
		"""[<channel>] <mode> <nick|hostmask|*> [<nick|hostmask|*>]

		sets -<mode> on them, if * found, remove them all"""
		b = self._removes(irc,msg,args,channel,mode,items)
		if not msg.nick == irc.nick and not b:
			irc.reply('unknown patterns, already removed or unsupported mode')
	undo = wrap(undo,['op','letter',many('something')])
	
	def uq (self, irc, msg, args, channel, items):
		"""[<channel>] <nick|hostmask|*> [<nick|hostmask|*>]

		sets -q on them, if * found, remove them all"""
		b = self._removes(irc,msg,args,channel,'q',items)
		if not msg.nick == irc.nick and not b:
			irc.reply('unknown patterns, already removed or unsupported mode')
	uq = wrap(uq,['op',many('something')])
	
	def ub (self, irc, msg, args, channel, items):
		"""[<channel>] <nick|hostmask|*> [<nick|hostmask>]

		sets -b on them, if * found, remove them all"""
		b = self._removes(irc,msg,args,channel,'b',items)
		if not msg.nick == irc.nick and not b:
			irc.reply('unknown patterns, already removed or unsupported mode')
	ub = wrap(ub,['op',many('something')])
	
	def ui (self, irc, msg, args, channel, items):
		"""[<channel>] <nick|hostmask|*> [<nick|hostmask|*>]

		sets -I on them, if * found, remove them all"""
		b = self._removes(irc,msg,args,channel,'I',items)
		if not msg.nick == irc.nick and not b:
			irc.reply('unknown patterns, already removed or unsupported mode')
	ui = wrap(ui,['op',many('something')])
	
	def ue (self, irc, msg, args, channel, items):
		"""[<channel>] <nick|hostmask|*> [<nick|hostmask|*>]

		sets -e on them, if * found, remove them all"""
		b = self._removes(irc,msg,args,channel,'e',items)
		if not msg.nick == irc.nick and not b:
			irc.reply('unknown patterns, already removed or unsupported mode')
	ue = wrap(ue,['op',many('something')])
	
	def remove (self,irc,msg,args,channel,nick,reason):
		"""[<channel>] <nick> [<reason>]
		
		force a part on <nick> with <reason> if provided"""
		chan = self.getChan(irc,channel)
		if not reason:
			reason = msg.nick
		chan.action.enqueue(ircmsgs.IrcMsg('REMOVE %s %s :%s' % (channel,nick,reason)))
		irc.replySuccess()
		self.forceTickle = True
		self._tickle(irc)
	remove = wrap(remove,['op','nickInChannel',additional('text')])
	
	def match (self,irc,msg,args,channel,prefix):
		"""[<channel>] <nick>

		returns active mode that targets nick given, nick must be in a channel shared by with the bot"""
		i = self.getIrc(irc)
		n = None
		if prefix in i.nicks:
			n = self.getNick(irc,prefix)
		else:
			irc.reply('unknow nick')
			return
		results = i.against(irc,channel,n,msg.prefix,self.getDb(irc.network))
		if len(results):
			irc.reply(' '.join(results), private=True)
		else:
			irc.reply('no results')
		self._tickle(irc)
	match = wrap(match,['op','text'])
	
	def check (self,irc,msg,args,channel,pattern):
		"""[<channel>] <pattern> 

		returns a list of affected users by a pattern"""
		if ircutils.isUserHostmask(pattern) or pattern.find(self.getIrcdExtbansPrefix(irc)) != -1:
			results = []
			i = self.getIrc(irc)
			for nick in list(irc.state.channels[channel].users):
				if nick in i.nicks:
					n = self.getNick(irc,nick)
					m = match(pattern,n,irc)
					if m:
						results.append('[%s - %s]' % (nick,m))
			if len(results):
				irc.reply('%s user(s): %s' % (len(results),' '.join(results)))
			else:
				irc.reply('nobody will be affected')
		else:
			irc.reply('invalid pattern given')
	check = wrap (check,['op','text'])
	
	def getmask (self,irc,msg,args,prefix):
		"""<nick|hostmask> 

		returns a list of hostmask's pattern, best first, mostly used for debug"""
		i = self.getIrc(irc)
		if prefix in i.nicks:
			irc.reply(' '.join(getBestPattern(self.getNick(irc,prefix),irc)))
		else:
			n = Nick(0)
			#gecos ( $x )
			if prefix.find('#') != -1:
				a = prefix.split('#')
				username = a[1]
				prefix = a[0]
				n.setPrefix(prefix)
				n.setUsername(username)
			else:
				n.setPrefix(prefix)
			if ircutils.isUserHostmask(prefix):
				irc.reply(' '.join(getBestPattern(n,irc)))
				return
			irc.reply('nick not found or wrong hostmask given')
	getmask = wrap(getmask,['owner','text'])
	
	def isvip (self,irc,msg,args,channel,nick):
		"""[<channel>] <nick> 

		tell if <nick> is vip in <channel>, mostly used for debug"""
		i = self.getIrc(irc)
		if nick in i.nicks:
			irc.reply(self._isVip(irc,channel,self.getNick(irc,nick)))
		else:
			irc.reply('nick not found')
	isvip = wrap(isvip,['op','nick'])
	
	def isbad (self,irc,msg,args,channel,nick):
		"""[<channel>] <nick> 

		tell if <nick> is flagged as bad in <channel>, mostly used for debug"""
		i = self.getIrc(irc)
		if nick in i.nicks:
			chan = self.getChan(irc,channel)
			irc.reply(chan.isWrong(getBestPattern(self.getNick(irc,nick),irc)[0]))
		else:
			irc.reply('nick not found')
	isbad = wrap(isbad,['op','nick'])
	
	#def supported (self,irc,msg,args):
		#"""
		
		#return supported modes by the ircd, for debug purpose"""
		#r = []
		#for item in irc.state.supported:
			#r.append('[%s: %s]' % (item,irc.state.supported[item]))
		#irc.reply(', '.join(r))
	#supported = wrap(supported,['owner'])

	def getIrcdMode (self,irc,mode,pattern):
		# here we try to know which kind of mode and pattern should be computed :
		# based on supported modes and extbans on the ircd
		# works for q in charibys, and should work for unreal and inspire
		if 'chanmodes' in irc.state.supported and mode == 'q':
			cm = irc.state.supported['chanmodes'].split(',')[0]
			if not mode in cm:
				if 'extban' in irc.state.supported:
					extban = irc.state.supported['extban']
					prefix = extban.split(',')[0]
					modes = extban.split(',')[1]
					if mode in modes:
						# unreal
						old = mode
						mode = 'b'
						if pattern and pattern.find(prefix) != 0:
							pattern = prefix + old + ':' + pattern
					elif 'm' in modes:
						# inspire ? 
						if pattern and pattern.find(prefix) != 0:
							pattern = prefix + 'm' + ':' + pattern
		return [mode,pattern]
	
	def getIrcdExtbansPrefix (self,irc):
		if 'extban' in irc.state.supported:
			return irc.state.supported['extban'].split(',')[0]
		return ''
	
	def _adds (self,irc,msg,args,channel,mode,items,duration,reason):
		i = self.getIrc(irc)
		targets = []
		if mode in self.registryValue('modesToAsk',channel=channel) or mode in self.registryValue('modesToAskWhenOpped',channel=channel):
			for item in items:
				if ircutils.isUserHostmask(item) or item.find(self.getIrcdExtbansPrefix(irc)) != -1:
					targets.append(item)
				elif item in i.nicks or item in irc.state.channels[channel].users:
					n = self.getNick(irc,item)
					patterns = getBestPattern(n,irc)
					# when resync patterns may be empty, until the bot computed WHO
					if len(patterns):
						targets.append(patterns[0])
		n = 0
		for item in targets:
			r = self.getIrcdMode(irc,mode,item)
			if i.add(irc,channel,r[0],r[1],duration,msg.prefix,self.getDb(irc.network)):
				if reason:
					f = None
					if self.registryValue('announceInTimeEditAndMark',channel=channel):
						if msg.prefix != irc.prefix and self.registryValue('announceMark',channel=channel):
							f = self._logChan
						elif msg.prefix == irc.prefix and self.registryValue('announceBotMark',channel=channel):
							f = self._logChan
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
		count = 0
		if mode in self.registryValue('modesToAsk',channel=channel) or mode in self.registryValue('modesToAskWhenOpped',channel=channel):
			for item in items:
				if ircutils.isUserHostmask(item) or item.find(self.getIrcdExtbansPrefix(irc)) != -1:
					targets.append(item)
				elif item in i.nicks or item in irc.state.channels[channel].users:
					n = self.getNick(irc,item)
					L = chan.getItemsFor(self.getIrcdMode(irc,mode,n.prefix)[0])
					# here we check active items against Nick and add everything pattern which matchs him
					for pattern in L:
						m = match(L[pattern].value,n,irc)
						if m:
							targets.append(L[pattern].value)
				elif item == '*':
					massremove = True
					targets = []
					if channel in list(irc.state.channels.keys()):
						L = chan.getItemsFor(self.getIrcdMode(irc,mode,'*!*@*')[0])
						for pattern in L:
							targets.append(L[pattern].value)
					break
			f = None
			if massremove:
				if self.registryValue('announceMassRemoval',channel=channel):
					f = self._logChan
			else:
				if msg.prefix != irc.prefix and self.registryValue('announceEdit',channel=channel):
					f = self._logChan
				elif msg.prefix == irc.prefix and self.registryValue('announceBotEdit',channel=channel):
					f = self._logChan
			for item in targets:
				r = self.getIrcdMode(irc,mode,item)
				if i.edit(irc,channel,r[0],r[1],0,msg.prefix,self.getDb(irc.network),None,f):
					count = count + 1
		self.forceTickle = True
		self._tickle(irc)
		return len(items) == count or massremove
	
	def getIrc (self,irc):
		# init irc db
		if not irc.network in self._ircs:
			i = self._ircs[irc.network] = Ircd (irc,self.registryValue('logsSize'))
			# restore CAP, if needed, needed to track account (account-notify) ang gecos (extended-join)
			# see config of this plugin
			irc.queueMsg(ircmsgs.IrcMsg('CAP LS'))
		return self._ircs[irc.network]

	def getChan (self,irc,channel):
		i = self.getIrc(irc)
		if not channel in i.channels:
			# restore channel state, loads lists
			modesToAsk = ''.join(self.registryValue('modesToAsk',channel=channel))
			modesWhenOpped = ''.join(self.registryValue('modesToAskWhenOpped',channel=channel))
			if channel in irc.state.channels:
				if irc.nick in irc.state.channels[channel].ops:
					if len(modesToAsk) or len(modesWhenOpped):
						for m in modesWhenOpped:
							i.queue.enqueue(ircmsgs.IrcMsg('MODE %s %s' % (channel,m)))
						for m in modesToAsk:
							i.lowQueue.enqueue(ircmsgs.IrcMsg('MODE %s %s' % (channel,m)))
				elif len(modesToAsk):
					for m in modesToAsk:
						i.lowQueue.enqueue(ircmsgs.IrcMsg('MODE %s %s' % (channel,m)))
				# schedule that for later
				# prevent the bot to disconnect itself is server takes too much time to answer
				i.lowQueue.enqueue(ircmsgs.ping(channel))
				# loads extended who
				i.lowQueue.enqueue(ircmsgs.IrcMsg('WHO ' + channel +' %tnuhiar,42')) # some ircd may not like this
				# fallback, TODO maybe uneeded as supybot do it by itself on join, but necessary on plugin reload ...
				i.lowQueue.enqueue(ircmsgs.ping(channel))
				i.lowQueue.enqueue(ircmsgs.IrcMsg('WHO %s' % channel))
				self.forceTickle = True
		return i.getChan (irc,channel)
	
	def getNick (self,irc,nick):
		return self.getIrc(irc).getNick(irc,nick)
	
	def makeDb(self, filename):
		"""Create a database and connect to it."""
		if os.path.exists(filename):
			db = sqlite3.connect(filename,timeout=10)
			db.text_factory = str
			return db
		db = sqlite3.connect(filename)
		db.text_factory = str
		c = db.cursor()
		c.execute("""CREATE TABLE bans (
				id INTEGER PRIMARY KEY,
				channel VARCHAR(1000) NOT NULL,
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
			irc.queueMsg(i.queue.dequeue())
		def f(L):
			return ircmsgs.modes(channel,L)
		for channel in list(irc.state.channels.keys()):
			chan = self.getChan(irc,channel)
			# check expired items
			for mode in list(chan.getItems().keys()):
				for value in list(chan._lists[mode].keys()):
					item = chan._lists[mode][value]
					if item.expire != None and item.expire != item.when and not item.asked and item.expire <= t:
						if mode == 'q' and item.value.find(self.getIrcdExtbansPrefix(irc)) == -1 and self.registryValue('useChanServForQuiets',channel=channel) and not irc.nick in irc.state.channels[channel].ops and not len(chan.queue):
							s = self.registryValue('unquietCommand')
							s = s.replace('$channel',channel)
							s = s.replace('$hostmask',item.value)
							i.queue.enqueue(ircmsgs.IrcMsg(s))
						else:
							chan.queue.enqueue(('-'+item.mode,item.value))
						# avoid adding it multi times until servers returns changes
						item.asked = True
						retickle = True
			# dequeue pending actions
			# log.debug('[%s] isOpped : %s, opAsked : %s, deopAsked %s, deopPending %s' % (channel,irc.nick in irc.state.channels[channel].ops,chan.opAsked,chan.deopAsked,chan.deopPending))
			# if chan.syn: # remove syn mandatory for support to unreal which doesn't like q list 
			if len(chan.queue):
				index = 0
				for item in list(chan.queue):
					(mode,value) = item
					if mode == '+q' and value.find(self.getIrcdExtbansPrefix(irc)) == -1 and self.registryValue('useChanServForQuiets',channel=channel) and not irc.nick in irc.state.channels[channel].ops and len(chan.queue) == 1:
						s = self.registryValue('quietCommand')
						s = s.replace('$channel',channel)
						s = s.replace('$hostmask',value)
						i.queue.enqueue(ircmsgs.IrcMsg(s))
						chan.queue.pop(index)
					index = index + 1
			if not irc.nick in irc.state.channels[channel].ops:
				chan.deopAsked = False
				chan.deopPending = False
			if chan.syn and not irc.nick in irc.state.channels[channel].ops and not chan.opAsked and self.registryValue('keepOp',channel=channel):
				# chan.syn is necessary, otherwise, bot can't call owner if rights missed ( see doNotice )
				if not self.registryValue('doNothingAboutOwnOpStatus',channel=channel):
					chan.opAsked = True
					irc.queueMsg(ircmsgs.IrcMsg(self.registryValue('opCommand',channel=channel).replace('$channel',channel).replace('$nick',irc.nick)))
					retickle = True
			if len(chan.queue) or len(chan.action):
				if not irc.nick in irc.state.channels[channel].ops and not chan.opAsked:
					# pending actions, but not opped
					if not chan.deopAsked:
						if not self.registryValue('doNothingAboutOwnOpStatus',channel=channel):
							chan.opAsked = True
							irc.queueMsg(ircmsgs.IrcMsg(self.registryValue('opCommand',channel=channel).replace('$channel',channel).replace('$nick',irc.nick)))
							retickle = True
				elif irc.nick in irc.state.channels[channel].ops:
					if not chan.deopAsked:
						if len(chan.queue):
							L = []
							index = 0
							adding = False
							while len(chan.queue):
								L.append(chan.queue.pop())
								if L[index][0].find ('+') != -1:
									adding = True
								index = index + 1
							# remove duplicates ( should not happens but .. )
							S = set(L)
							r = []
							for item in L:
								r.append(item)
							# if glich, just comment this if...
							if not len(chan.action) and not adding:
								if not self.registryValue('keepOp',channel=channel) and not self.registryValue('doNothingAboutOwnOpStatus',channel=channel):
									chan.deopPending = True
									chan.deopAsked = True
									r.append(('-o',irc.nick))
							if len(r):
								# create IrcMsg
								self._sendModes(irc,r,f)
						if len(chan.action):
							while len(chan.action):
								i.queue.enqueue(chan.action.pop())
					else:
						retickle = True
		# send waiting msgs
		while len(i.queue):
			irc.queueMsg(i.queue.dequeue())
		# updates duration
		for channel in list(irc.state.channels.keys()):
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
					for update in list(chan.update.keys()):
						L.append(chan.update[update])
					o = {}
					index = 0
					for k in L:
						(m,value,expire,prefix) = L[index]
						if expire == -1 or expire is None:
							if overexpire != expire:
								chan.update['%s%s' % (m,value)] = [m,value,overexpire,irc.prefix]
						index = index + 1
				L = []
				for update in list(chan.update.keys()):
					L.append(chan.update[update])
				for update in L:
					(m,value,expire,prefix) = update
					# todo need to protect cycle call between i.edit scheduler and _tickle here.
					item = chan.getItem(m,value)
					if item and item.expire != expire:
						f = None
						if self.registryValue('announceInTimeEditAndMark',channel=item.channel):
							if prefix != irc.prefix and self.registryValue('announceEdit',channel=item.channel):
								f = self._logChan
							elif prefix == irc.prefix and self.registryValue('announceBotEdit',channel=item.channel):
								f = self._logChan
						key = '%s%s' % (m,value)
						del chan.update[key]
						b = i.edit(irc,item.channel,item.mode,item.value,expire,prefix,self.getDb(irc.network),self._schedule,f)
						retickle = True
			# update marks
			if len(chan.mark):
				L = []
				for mark in list(chan.mark.keys()):
					L.append(chan.mark[mark])
				for mark in L:
					(m,value,reason,prefix) = mark
					item = chan.getItem(m,value)
					if item:
						f = None
						if self.registryValue('announceInTimeEditAndMark',channel=item.channel):
							if prefix != irc.prefix and self.registryValue('announceMark',channel=item.channel):
								f = self._logChan
							elif prefix == irc.prefix and self.registryValue('announceBotMark',channel=item.channel):
								f = self._logChan
						i.mark(irc,item.uid,reason,prefix,self.getDb(irc.network),f)
						key = '%s%s' % (item.mode,value)
						del chan.mark[key]
			if irc.nick in irc.state.channels[channel].ops and not self.registryValue('keepOp',channel=channel) and not chan.deopPending and not chan.deopAsked:
				# ask for deop, delay it a bit
				if not self.registryValue('doNothingAboutOwnOpStatus',channel=channel):
					self.unOp(irc,channel)
			# moslty logChannel, and maybe few sync msgs
			if len(i.lowQueue):
				retickle = True
				while len(i.lowQueue):
					irc.queueMsg(i.lowQueue.dequeue())
		if retickle:
			self.forceTickle = True
		else:
			self.forceTickle = False
	
	def _addChanModeItem (self,irc,channel,mode,value,prefix,date):
		# bqeI* -ov
		if irc.isChannel(channel) and channel in irc.state.channels:
			if mode in self.registryValue('modesToAsk',channel=channel) or mode in self.registryValue('modesToAskWhenOpped',channel=channel):
				chan = self.getChan(irc,channel)
				chan.addItem(mode,value,prefix,float(date),self.getDb(irc.network),False)
	
	def _endList (self,irc,msg,channel,mode):
		if irc.isChannel(channel) and channel in irc.state.channels:
			chan = self.getChan(irc,channel)
			b = False
			if not mode in chan.dones:
				chan.dones.append(mode)
				b = True
			i = self.getIrc(irc)
			f = None
			if self.registryValue('announceModeSync',channel=channel):
				f = self._logChan
				if b:
					self._logChan(irc,channel,'[%s] sync %s' % (channel,chan.dones))
			i.resync(irc,channel,mode,self.getDb(irc.network),f)
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
		chan = self.getChan(irc,msg.args[1])
		chan.nicks[nick] = True
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
			prefix = '%s!%s@%s' % (nick,ident,host)
			if n.ip == None and ip != '255.255.255.255':
				# validate ip
				n.setIp(ip)
			n.setPrefix(prefix)
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
				chan.syn = True
				if self.registryValue('announceModeSync',channel=channel):
					self._logChan(irc,channel,"[%s] is ready" % channel)
		self._tickle(irc)
	
	def _logChan (self,irc,channel,message):
		# send messages to logChannel if configured for
		if channel in irc.state.channels:
			logChannel = self.registryValue('logChannel',channel=channel)
			if logChannel in irc.state.channels:
				i = self.getIrc(irc)
				i.lowQueue.enqueue(ircmsgs.privmsg(logChannel,message))
				self.forceTickle = True
	
	def doJoin (self,irc,msg):
		channels = msg.args[0].split(',')
		n = self.getNick(irc,msg.nick)
		n.setPrefix(msg.prefix)
		i = self.getIrc(irc)
		if 'LIST' in i.caps and 'extended-join' in i.caps['LIST'] and len(msg.args) == 3:
			n.setRealname(msg.args[2])
			n.setAccount(msg.args[1])
		best = getBestPattern(n,irc)[0]
		if msg.nick == irc.nick:
			return
		for channel in channels:
			if ircutils.isChannel(channel) and channel in irc.state.channels:
				chan = self.getChan(irc,channel)
				chan.nicks[msg.nick] = True
				n.addLog(channel,'has joined')
				c = ircdb.channels.getChannel(channel)
				banned = False
				if not self._isVip(irc,channel,n):
					if c.bans and len(c.bans) and self.registryValue('useChannelBansForPermanentBan',channel=channel):
						for ban in list(c.bans):
							if match (ban,n,irc):
								if i.add(irc,channel,'b',best,self.registryValue('autoExpire',channel=channel),irc.prefix,self.getDb(irc.network)):
									banned = True
									self.forceTickle = True
									break
					if not banned:
						isMassJoin = self._isSomething(irc,channel,channel,'massJoin')
						if isMassJoin:
							chan.action.enqueue(ircmsgs.IrcMsg('MODE %s %s' % (channel,self.registryValue('massJoinMode',channel=channel))))
							def unAttack():
								if channel in list(irc.state.channels.keys()):
									chan.action.enqueue(ircmsgs.IrcMsg('MODE %s %s' % (channel,self.registryValue('massJoinUnMode',channel=channel))))
							schedule.addEvent(unAttack,float(time.time()+self.registryValue('massJoinDuration',channel=channel)))
							self.forceTickle = True
							
		if msg.nick == irc.nick:
			self.forceTickle = True
		self._tickle(irc)
	
	def doPart (self,irc,msg):
		isBot = msg.prefix == irc.prefix
		channels = msg.args[0].split(',')
		i = self.getIrc(irc)
		n = self.getNick(irc,msg.nick)
		n.setPrefix(msg.prefix)
		reason = ''
		best = getBestPattern(n,irc)[0]
		if len(msg.args) == 2:
			reason = msg.args[1].lstrip().rstrip()
		canRemove = True
		for channel in channels:
			if isBot and channel in i.channels:
				del i.channels[channel]
				continue
			if ircutils.isChannel(channel) and channel in irc.state.channels:
				if len(reason):
					if reason.startswith('requested by') and self.registryValue('announceKick',channel=channel):
						self._logChan(irc,channel,'[%s] %s has left (%s)' % (channel,msg.prefix,reason))
					n.addLog(channel,'has left [%s]' % (reason))
				else:
					n.addLog(channel,'has left')
				if not isBot:
					chan = self.getChan(irc,channel)
					if msg.nick in chan.nicks:
						del chan.nicks[msg.nick]
					if msg.nick in irc.state.channels[channel].users:
						canRemove = False
					if not self._isVip(irc,channel,n):
						isCycle = self._isSomething(irc,channel,best,'cycle')
						if isCycle:
							isBad = self._isSomething(irc,channel,best,'bad')
							kind = None
							if isBad:
								kind = 'bad'
							else:
								kind = 'cycle'
							mode = self.registryValue('%sMode' % kind,channel=channel)
							duration = self.registryValue('%sDuration' % kind,channel=channel)
							comment = self.registryValue('%sComment' % kind,channel=channel)
							self._act(irc,channel,mode,best,duration,comment)
							self.forceTickle = True
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
			i = self.getIrc(irc)
			if ircutils.isChannel(channel) and channel in i.channels:
				del i.channels[channel]
				self._tickle(irc)
				return
		else:
			chan = self.getChan(irc,channel)
			if msg.nick in chan.nicks:
				del chan.nicks[msg.nick]
		n = self.getNick(irc,target)
		n.addLog(channel,'kicked by %s (%s)' % (msg.prefix,reason))
		if self.registryValue('announceKick',channel=channel):
			self._logChan(irc,channel,'[%s] %s kicked by %s (%s)' % (channel,n.prefix,msg.prefix,reason))
		if len(reason) and msg.prefix != irc.prefix and self.registryValue('addKickMessageInComment',channel=channel):
			chan = self.getChan(irc,channel)
			found = None
			for mode in self.registryValue('modesToAsk',channel=channel):
				items = chan.getItemsFor(mode)
				for k in items:
					item = items[k]
					f = match(item.value,n,irc)
					if f:
						found = item
						break
				if found:
					break
			if found:
				f = None
				if self.registryValue('announceBotMark',channel=channel):
					f = self._logChan
				i.mark(irc,found.uid,'kicked by %s (%s)' % (msg.nick,reason),irc.prefix,self.getDb(irc.network),f)
		self._tickle(irc)

	def _rmNick (self,irc,n):
		def nrm():
			patterns = getBestPattern(n,irc)
			i = self.getIrc(irc)
			if not len(patterns):
				return
			found = False
			(nick,ident,hostmask) = ircutils.splitHostmask(n.prefix)
			for channel in irc.state.channels:
				if nick in irc.state.channels[channel].users:
					 found = True
			if not found:
				if nick in i.nicks:
					del i.nicks[nick]
				best = patterns[0]
				for channel in irc.state.channels:
					if channel in i.channels:
						chan = self.getChan(irc,channel)
						if nick in chan.nicks:
							del chan.nicks[nick]
						if best in chan.repeatLogs:
							del chan.repeatLogs[best]
						for k in chan.spam:
							if best in chan.spam[k]:
								del chan.spam[k][best]
		schedule.addEvent(nrm,time.time()+self.registryValue('cycleLife')+10)
	
	def doQuit (self,irc,msg):
		isBot = msg.nick == irc.nick
		reason = None
		if len(msg.args) == 1:
			reason = msg.args[0].lstrip().rstrip()
		removeNick = True
		if not isBot:
			n = self.getNick(irc,msg.nick)
			patterns = getBestPattern(n,irc)
			best = None
			if len(patterns):
				best = patterns[0]
			if reason:
				n.addLog('ALL','has quit [%s]' % reason)
			else:
				n.addLog('ALL','has quit')
				#,'Excess Flood','Max SendQ exceeded'
			if reason and reason in ['Changing host']:
				# keeping this nick, may trigger cycle check
				removeNick = False
			elif reason and reason.startswith('Killed (') or reason.startswith('K-Lined'):
				if reason.find('Nickname regained by services') == -1:
					for channel in irc.state.channels:
						chan = self.getChan(irc,channel)
						if msg.nick in chan.nicks:
							if self.registryValue('announceKick',channel=channel):
								self._logChan(irc,channel,'[%s] %s has quit (%s)' % (channel,msg.prefix,reason))
			for channel in irc.state.channels:
				chan = self.getChan(irc,channel)
				if msg.nick in chan.nicks:
					if not self._isVip(irc,channel,n):
						isCycle = self._isSomething(irc,channel,best,'cycle')
						if isCycle:
							isBad = self._isSomething(irc,channel,best,'bad')
							kind = None
							if isBad:
								kind = 'bad'
							else:
								kind = 'cycle'
							mode = self.registryValue('%sMode' % kind,channel=channel)
							duration = self.registryValue('%sDuration' % kind,channel=channel)
							comment = self.registryValue('%sComment' % kind,channel=channel)
							self._act(irc,channel,mode,best,duration,comment)
							self.forceTickle = True
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
			del i.nicks[oldNick]
			if n.prefix:
				prefixNew = '%s!%s' % (newNick,n.prefix.split('!')[1])
				n.setPrefix(prefixNew)
			i.nicks[newNick] = n
			n = self.getNick(irc,newNick)
			n.addLog('ALL','%s is now known as %s' % (oldNick,newNick))
			best = None
			patterns = getBestPattern(n,irc)
			if len(patterns):
				best = patterns[0]
			if not best:
				return
			for channel in irc.state.channels:
				if newNick in irc.state.channels[channel].users:
					chan = self.getChan(irc,channel)
					if oldNick in chan.nicks:
						del chan.nicks[oldNick]
					chan.nicks[msg.nick] = True
					if self._isVip(irc,channel,n):
						continue
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
					# len(cap) == 1 prevents weired behaviour with CommaSeparatedListOfStrings
					if len(cap) != 1 and cap in i.caps['LS'] and not cap in i.caps['LIST']:
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
		n = None
		if ircutils.isUserHostmask(msg.prefix):
			nick = ircutils.nickFromHostmask(msg.prefix)
			n = self.getNick(irc,nick)
			acc = msg.args[0]
			old = n.account
			if acc == '*':
				acc = None
			n.setAccount(acc)
			n.addLog('ALL','%s is now identified as %s' % (old,acc))
		else:
			return
		if n and n.account and n.ip:
			i = self.getIrc(irc)
			for channel in irc.state.channels:
				if self.registryValue('checkEvade',channel=channel):
					if nick in irc.state.channels[channel].users:
						modes = self.registryValue('modesToAsk',channel=channel)
						found = False
						chan = self.getChan(irc,channel)
						for mode in modes:
							if mode == 'b':
								items = chan.getItemsFor(mode)
								for item in items:
									# only check against ~a:,$a: bans
									if items[item].value.startswith(self.getIrcdExtbansPrefix(irc)) and items[item].value[1] == 'a':
										f = match(items[item].value,n,irc)
										if f:
											found = items[item]
										if found:
											break
									if found:
										break
						if found:
							duration = -1
							if found.expire and found.expire != found.when:
								duration = int(found.expire-time.time())
							self._act (irc,channel,found.mode,getBestPattern(n,irc)[0],duration,'evade of [#%s +%s %s]' % (found.uid,found.mode,found.value))
							f = None
							if self.registryValue('announceBotMark',channel=found.channel):
								f = self._logChan
							i.mark(irc,found.uid,'evade with %s --> %s' % (msg.prefix,getBestPattern(n,irc)[0]),irc.prefix,self.getDb(irc.network),f)
							self.forceTickle = True
						
		self._tickle(irc)
	
	def doNotice (self,irc,msg):
		(targets, text) = msg.args
		if not ircutils.isUserHostmask(irc.prefix):
			return
		if targets == irc.nick:
			b = False
			# todo keep this code commented until request to implement it
			#b = False
			#if text == 'You are not authorized to perform this operation.':
				#b = True
			#if b:
				#i = self.getIrc(irc)
				#for nick in i.nicks:
					#n = i.getNick(irc,nick)
					#if n.prefix and ircdb.checkCapability(n.prefix, 'owner') and n.prefix != irc.prefix:
						#irc.queueMsg(ircmsgs.privmsg(n.prefix.split('!')[0],'Warning got %s notice: %s' % (msg.prefix,text)))
						#break
			#if text.startswith('*** Message to ') and text.endswith(' throttled due to flooding'):
				# as bot floods, todo schedule info to owner
		else:
			if msg.nick == irc.nick:
				return
			n = self.getNick(irc,msg.nick)
			patterns = getBestPattern(n,irc)
			best = False
			if len(patterns):
				best = patterns[0]
			if not best:
				return
			for channel in targets.split(','):
				if irc.isChannel(channel) and channel in irc.state.channels:
					chan = self.getChan(irc,channel)
					n.addLog(channel,'NOTICE | %s' % text)
					isVip = self._isVip(irc,channel,n)
					if not isVip:
						isNotice = self._isSomething(irc,channel,best,'notice')
						isMass = self._isMassRepeat(irc,channel,text)
						isBad = False
						if isMass:
							kind = 'massRepeat'
							mode = self.registryValue('%sMode' % kind,channel=channel)
							duration = self.registryValue('%sDuration' % kind,channel=channel)
							comment = self.registryValue('%sComment' % kind,channel=channel)
							self._act(irc,channel,mode,best,duration,comment)
							self._isBad(irc,channel,best)
							self.forceTickle = True
						if isNotice:
							isBad = self._isSomething(irc,channel,best,'bad')
						if isNotice or isBad:
							kind = None
							if isBad:
								kind = 'bad'
							else:
								kind = 'notice'
							mode = self.registryValue('%sMode' % kind,channel=channel)
							duration = self.registryValue('%sDuration' % kind,channel=channel)
							comment = self.registryValue('%sComment' % kind,channel=channel)
							self._act(irc,channel,mode,best,duration,comment)
							self.forceTickle = True
					if self.registryValue('announceNotice',channel=channel):
						if not chan.isWrong(best):
							self._logChan(irc,channel,'[%s] %s notice "%s"' % (channel,msg.prefix,text))
						
		self._tickle(irc)
	
	def _schedule(self,irc,end):
		if end > time.time():
			def do():
				self.forceTickle = True
				self._tickle(irc)
			schedule.addEvent(do,end)
		else:
			self.forceTickle = True
			self._tickle(irc)
		
	def _isVip (self,irc,channel,n):
		protected = ircdb.makeChannelCapability(channel, 'protected')
		if ircdb.checkCapability(n.prefix, protected):
			return True
		chan = self.getChan(irc,channel)
		ignoresModes = self.registryValue('modesToAskWhenOpped',channel=channel)
		vip = False
		for ignore in ignoresModes:
			items = chan.getItemsFor(ignore)
			if items:
				for item in items:
					if match(item,n,irc):
						vip = True
						break
			if vip:
				break
		return vip
	
	def doPrivmsg (self,irc,msg):
		if msg.nick == irc.nick:
			self._tickle(irc)
			return
		try:
			(recipients, text) = msg.args
		except:
			return
		isAction = ircmsgs.isAction(msg)
		isCtcpMsg = ircmsgs.isCtcp(msg)
		if isAction:
			text = ircmsgs.unAction(msg)
		n = None
		best = None
		patterns = None
		i = self.getIrc(irc)
		if ircutils.isUserHostmask(msg.prefix):
			n = self.getNick(irc,msg.nick)
			patterns = getBestPattern(n,irc)
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
				elif isAction:
					message = '- %s -' % text
				n.addLog(channel,message)
				# protection features
				isVip = self._isVip(irc,channel,n)
				# checking if message matchs living massRepeatPattern
				if not isVip:
					isCtcp = False
					if isCtcpMsg and not isAction:
						isCtcp = self._isSomething(irc,channel,best,'ctcp')
					isFlood = self._isFlood(irc,channel,best)
					isLowFlood = self._isLowFlood(irc,channel,best)
					isRepeat = self._isRepeat(irc,channel,best,text)
					isHilight = self._isHilight(irc,channel,best,text)
					isCap = self._isCap(irc,channel,best,text)
					isMass = self._isMassRepeat(irc,channel,text)
					if isMass:
						kind = 'massRepeat'
						mode = self.registryValue('%sMode' % kind,channel=channel)
						duration = self.registryValue('%sDuration' % kind,channel=channel)
						comment = self.registryValue('%sComment' % kind,channel=channel)
						self._act(irc,channel,mode,best,duration,comment)
						self._isBad(irc,channel,best)
						self.forceTickle = True
					if isFlood or isHilight or isRepeat or isCap or isCtcp or isLowFlood:
						isBad = self._isBad(irc,channel,best)
						kind = None
						duration = 0
						if isBad:
							kind = 'bad'
							duration = self.registryValue('badDuration',channel=channel)
						else:
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
				if not chan.isWrong(best):
					# prevent the bot to flood logChannel with bad user craps
					if self.registryValue('announceCtcp',channel=channel) and isCtcpMsg and not isAction:
						self._logChan(irc,channel,'[%s] %s ctcps "%s"' % (channel,msg.prefix,text))
						self.forceTickle = True
					else:
						if self.registryValue('announceOthers',channel=channel) and irc.nick in irc.state.channels[channel].ops and 'z' in irc.state.channels[channel].modes:
							message = None
							if 'm' in irc.state.channels[channel].modes:
								if not msg.nick in irc.state.channels[channel].voices and not msg.nick in irc.state.channels[channel].ops:
									message = '[%s] [+m] <%s> %s' % (channel,msg.prefix,text)
							if not message:
								if not msg.nick in irc.state.channels[channel].voices and not msg.nick in irc.state.channels[channel].ops:
									modes = self.registryValue('modesToAsk',channel=channel)
									found = False
									for mode in modes:
										items = chan.getItemsFor(mode)
										for item in items:
											f = match(items[item].value,n,irc)
											if f:
												found = [items[item],f]
											if found:
												break
										if found:
											break
									if found:
										message = '[%s] [#%s +%s %s] <%s> %s' % (channel,found[0].uid,found[0].mode,found[0].value,msg.nick,text)
							if message:
								self._logChan(irc,channel,message)
			elif irc.nick == channel:
				found = self.hasAskedItems(irc,msg.prefix,True)
				if found:
					tokens = callbacks.tokenize('ChanTracker editAndMark %s %s' % (found[0],text))
					msg.command = 'PRIVMSG'
					msg.prefix = msg.prefix
					self.Proxy(irc.irc, msg, tokens)
				found = self.hasAskedItems(irc,msg.prefix,False)
				if found:
					log.debug('hasAsked %s' % found[0])
					i.lowQueue.enqueue(ircmsgs.privmsg(msg.nick,found[5]))
					self.forceTickle = True
		self._tickle(irc)
	
	def hasAskedItems(self,irc,prefix,remove):
		i = self.getIrc(irc)
		if prefix in i.askedItems:
			found = None
			for item in i.askedItems[prefix]:
				if not found or item < found[0]:
					found = i.askedItems[prefix][item]
			if found:
				chan = self.getChan(irc,found[3])
				items = chan.getItemsFor(found[1])
				active = None
				if len(items):
					for item in items:
						item = items[item]
						if item.uid == found[0]:
							active = item;
							break
				if remove:
					del i.askedItems[prefix][found[0]]
					if not len(i.askedItems[prefix]):
						del i.askedItems[prefix]
				if active:
					return found
		return None

	def addToAsked (self,irc,prefix,data,nick):
		toAsk = False
		endTime = time.time() + 180
		i = self.getIrc(irc)
		if not prefix in i.askedItems:
			i.askedItems[prefix] = {}
			toAsk = True
		i.askedItems[prefix][data[0]] = data
		if toAsk:
			i.lowQueue.enqueue(ircmsgs.privmsg(nick,data[5]))
                        self.forceTickle = True
		def unAsk():
			if prefix in i.askedItems:
				if data[0] in i.askedItems[prefix]:
					del i.askedItems[prefix][data[0]]
				if not len(list(i.askedItems[prefix])):
					del i.askedItems[prefix]
			found = self.hasAskedItems(irc,prefix,False)
			if found:
				i.lowQueue.enqueue(ircmsgs.privmsg(nick,found[5]))
				self.forceTickle
		schedule.addEvent(unAsk,time.time() + 180 * len(list(i.askedItems[prefix])))				

	def doTopic(self, irc, msg):
		if len(msg.args) == 1:
			return
		if ircutils.isUserHostmask(msg.prefix):
			n = self.getNick(irc,msg.nick)
		channel = msg.args[0]
		if channel in irc.state.channels:
			if n:
				n.addLog(channel,'sets topic "%s"' % msg.args[1])
			if self.registryValue('announceTopic',channel=channel):
				self._logChan(irc,channel,'[%s] %s sets topic "%s"' % (channel,msg.prefix,msg.args[1]))
				self.forceTickle = True
		self._tickle(irc)
	
	def unOp (self,irc,channel):
		# remove irc.nick from op, if nothing pending
		if channel in irc.state.channels:
			i = self.getIrc(irc)
			chan = self.getChan(irc,channel)
			if chan.deopPending:
				return
			def unOpBot():
				if channel in irc.state.channels:
					if not len(i.queue) and not len(chan.queue):
						if irc.nick in irc.state.channels[channel].ops and not self.registryValue('keepOp',channel=channel):
							if not chan.deopAsked:
								chan.deopPending = False
								chan.deopAsked = True
								irc.queueMsg(ircmsgs.IrcMsg('MODE %s -o %s' % (channel,irc.nick)))
								# little trick here, tickle before setting deopFlag
								self.forceTickle = True
								self._tickle(irc)
					else:
						# reask for deop
						if irc.nick in irc.state.channels[channel].ops and not self.registryValue('keepOp',channel=channel) and not chan.deopAsked:
							self.deopPending = False
							self.unOp(irc,channel)
			chan.deopPending = True
			schedule.addEvent(unOpBot,float(time.time()+10))
			
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
		db = self.getDb(irc.network)
		c = db.cursor()
		toCommit = False
		toexpire = []
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
						if m in self.registryValue('modesToAskWhenOpped',channel=channel) or m in self.registryValue('modesToAsk',channel=channel):
							item = chan.addItem(m,value,msg.prefix,now,self.getDb(irc.network))
							if msg.nick != irc.nick and self.registryValue('askOpAboutMode',channel=channel) and ircdb.checkCapability(msg.prefix, '%s,op' % channel):
								data = [item.uid,m,value,channel,msg.prefix,'For [#%s +%s %s in %s] type <duration> <reason>, you have 3 minutes' % (item.uid,m,value,channel)]
								self.addToAsked (irc,msg.prefix,data,msg.nick)
							if overexpire > 0:
								if msg.nick != irc.nick:
									toexpire.append(item)
						# here bot could add others mode changes or actions
						if item and len(item.affects):
							for affected in item.affects:
								nick = affected.split('!')[0]
								if self._isVip(irc,channel,self.getNick(irc,nick)):
									continue
								kicked = False
								if m in self.registryValue('kickMode',channel=channel) and msg.nick == irc.nick: #  and not value.startswith(self.getIrcdExtbans(irc)) works for unreal
									if nick in irc.state.channels[channel].users and nick != irc.nick:
										chan.action.enqueue(ircmsgs.kick(channel,nick,self.registryValue('kickMessage',channel=channel)))
										self.forceTickle = True
										kicked = True
								if not kicked and m in self.registryValue('modesToAsk',channel=channel) and self.registryValue('doActionAgainstAffected',channel=channel):
									if nick in irc.state.channels[channel].ops and not nick == irc.nick:
										chan.queue.enqueue(('-o',nick))
									if nick in irc.state.channels[channel].halfops and not nick == irc.nick:
										chan.queue.enqueue(('-h',nick))
									if nick in irc.state.channels[channel].voices and not nick == irc.nick:
										chan.queue.enqueue(('-v',nick))
							self.forceTickle = True
						# bot just got op
						if m == 'o' and value == irc.nick:
							chan.opAsked = False
							chan.deopPending = False
							ms = ''
							asked = self.registryValue('modesToAskWhenOpped',channel=channel)
							asked = ''.join(asked)
							asked = asked.replace(',','')
							for k in asked:
								if not k in chan.dones:
									irc.queueMsg(ircmsgs.IrcMsg('MODE %s %s' % (channel,k)))
							# flush pending queue, if items are waiting
							self.forceTickle = True
					else:
						m = mode[1:]
						if m == 'o' and value == irc.nick:
							# prevent bot to sent many -o modes when server takes time to reply
							chan.deopAsked = False
						if m in self.registryValue('modesToAskWhenOpped',channel=channel) or m in self.registryValue('modesToAsk',channel=channel):
							toCommit = True
							item = chan.removeItem(m,value,msg.prefix,c)
					if n:
						n.addLog(channel,'sets %s %s' % (mode,value))
					if item:
						if '+' in mode:
							if not len(item.affects):
								if self.registryValue('announceMode',channel=channel):
									msgs.append('[#%s %s %s]' % (str(item.uid),mode,value))
							elif len(item.affects) != 1:
								if self.registryValue('announceMode',channel=channel):
									msgs.append('[#%s %s %s - %s users]' % (str(item.uid),mode,value,str(len(item.affects))))
							else:
								if self.registryValue('announceMode',channel=channel):
									msgs.append('[#%s %s %s - %s]' % (str(item.uid),mode,value,item.affects[0]))
						else:
							if not len(item.affects):
								if self.registryValue('announceMode',channel=channel):
									msgs.append('[#%s %s %s %s]' % (str(item.uid),mode,value,str(utils.timeElapsed(item.removed_at-item.when))))
							elif len(item.affects) != 1:
								if self.registryValue('announceMode',channel=channel):
									msgs.append('[#%s %s %s - %s users, %s]' % (str(item.uid),mode,value,str(len(item.affects)),str(utils.timeElapsed(item.removed_at-item.when))))
							else:
								if self.registryValue('announceMode',channel=channel):
									msgs.append('[#%s %s %s - %s, %s]' % (str(item.uid),mode,value,item.affects[0],str(utils.timeElapsed(item.removed_at-item.when))))
					else:
						if mode.find ('o') != -1 or mode.find('h') != -1 or mode.find ('v') != -1:
							if self.registryValue('announceVoiceAndOpMode',channel=channel):
								msgs.append('[%s %s]' % (mode,value))
						else:
							msgs.append('[%s %s]' % (mode,value))
				else:
					if n:
						n.addLog(channel,'sets %s' % mode)
					msgs.append(mode)
			if toCommit:
				db.commit()
			c.close()
			if irc.nick in irc.state.channels[channel].ops and not self.registryValue('keepOp',channel=channel):
				self.forceTickle = True
			if self.registryValue('announceMode',channel=channel) and len(msgs):
				self._logChan(irc,channel,'[%s] %s sets %s' % (channel,msg.nick,' '.join(msgs)))
				self.forceTickle = True
			if len(toexpire):
				for item in toexpire:
					f = None
					if self.registryValue('announceBotEdit',channel=item.channel):
						f = self._logChan
					i.edit(irc,item.channel,item.mode,item.value,self.registryValue('autoExpire',channel=item.channel),irc.prefix,self.getDb(irc.network),self._schedule,f)
				self.forceTickle = True
		self._tickle(irc)
	
	def do474(self,irc,msg):
		# bot banned from a channel it's trying to join
		# server 474 irc.nick #channel :Cannot join channel (+b) - you are banned
		# TODO talk with owner
		self._tickle(irc)
		
	def do478(self,irc,msg):
		# message when ban list is full after adding something to eqIb list
		(nick,channel,ban,info) = msg.args
		if info == 'Channel ban list is full':
			if self.registryValue('logChannel',channel=channel) in irc.state.channels:
				L = []
				for user in list(irc.state.channels[self.registryValue('logChannel',channel=channel)].users):
					L.append(user)
				self._logChan(irc,channel,'[%s] %s : %s' % (channel,info,' '.join(L)))
		self._tickle(irc)
	
	 # protection features
	
	def _act (self,irc,channel,mode,mask,duration,reason):
		if mode in self.registryValue('modesToAsk',channel=channel) or mode in self.registryValue('modesToAskWhenOpped',channel=channel):
			i = self.getIrc(irc)
			if i.add(irc,channel,mode,mask,duration,irc.prefix,self.getDb(irc.network)):
				if reason and len(reason):
					f = None
					if self.registryValue('announceInTimeEditAndMark',channel=channel):
						if self.registryValue('announceBotMark',channel=channel):
							f = self._logChan
					i.submark(irc,channel,mode,mask,reason,irc.prefix,self.getDb(irc.network),f)
			else:
				# increase duration, until the wrong action stopped
				f = None
				if self.registryValue('announceBotEdit',channel=channel):
					f = self._logChan
				chan = self.getChan(irc,channel)
				item = chan.getItem(mode,mask)
				oldDuration = int(item.expire-item.when)
				i.edit(irc,channel,mode,mask,int(oldDuration+duration),irc.prefix,self.getDb(irc.network),self._schedule,f)
				if reason and len(reason):
					f = None
					if self.registryValue('announceBotMark',channel=channel):
						f = self._logChan
					i.mark(irc,item.uid,reason,irc.prefix,self.getDb(irc.network),f)
			self.forceTickle = True
			self._tickle(irc)
		else:
			results = []
			i = self.getIrc(irc)
			for nick in list(irc.state.channels[channel].users):
				if nick in i.nicks and nick != irc.nick:
					n = self.getNick(irc,nick)
					m = match(mask,n,irc)
					if m:
						results.append(nick)
			if len(results) and mode in 'kr':
				chan = self.getChan(irc,channel)
				if not reason or not len(reason):
					reason = self.registryValue('kickMessage',channel=channel)
				for n in results:
					if mode == 'k':
						chan.action.enqueue(ircmsgs.IrcMsg('KICK %s %s :%s' % (channel,n,reason)))
						self.forceTickle = True
					elif mode == 'r':
						chan.action.enqueue(ircmsgs.IrcMsg('REMOVE %s %s :%s' % (channel,n,reason)))
						self.forceTickle = True
				self._tickle(irc)
			else:
				log.error('%s %s %s %s %s unsupported mode' % (channel,mode,mask,duration,reason))
	
	def _isSomething (self,irc,channel,key,prop):
		limit = self.registryValue('%sPermit' % prop,channel=channel)
		if limit < 0:
			return False
		chan = self.getChan(irc,channel)
		life = self.registryValue('%sLife' % prop,channel=channel)
		if not prop in chan.spam:
			chan.spam[prop] = {}
		if not key in chan.spam[prop] or chan.spam[prop][key].timeout != life:
			chan.spam[prop][key] = utils.structures.TimeoutQueue(life)
		chan.spam[prop][key].enqueue(key)
		if len(chan.spam[prop][key]) > limit:
			log.debug('[%s] %s is detected as %s' % (channel,key,prop))
			chan.spam[prop][key].reset()
			return True
		return False
	
	def _isBad (self,irc,channel,key):
		b = self._isSomething(irc,channel,key,'bad')
		if b:
			if self._isSomething(irc,channel,channel,'attack'):
				# if number of bad users raise the allowed limit, bot has to set channel attackmode
				chan = self.getChan(irc,channel)
				chan.action.enqueue(ircmsgs.IrcMsg('MODE %s %s' % (channel,self.registryValue('attackMode',channel=channel))))
				def unAttack():
					if channel in list(irc.state.channels.keys()):
						chan.action.enqueue(ircmsgs.IrcMsg('MODE %s %s' % (channel,self.registryValue('attackUnMode',channel=channel))))
				schedule.addEvent(unAttack,float(time.time()+self.registryValue('attackDuration',channel=channel)))
		return b
	
	def _isFlood(self,irc,channel,key):
		return self._isSomething(irc,channel,key,'flood')
	
	def _isLowFlood(self,irc,channel,key):
		return self._isSomething(irc,channel,key,'lowFlood')
	
	def _isHilight (self,irc,channel,key,message):
		limit = self.registryValue('hilightPermit',channel=channel)
		if limit == -1:
			return False
		count = 0
		messages = message.split(' ')
		users = []
		for user in list(irc.state.channels[channel].users):
			users.append(user)
		for m in messages:
			for user in users:
				if m == user:
					count = count + 1
					break
		return count > limit
	
	def _isRepeat(self,irc,channel,key,message):
		if self.registryValue('repeatPermit',channel=channel) < 0:
			return False
		chan = self.getChan(irc,channel)
		timeout = self.registryValue('repeatLife',channel=channel)
		if not key in chan.repeatLogs or chan.repeatLogs[key].timeout != timeout:
			chan.repeatLogs[key] = utils.structures.TimeoutQueue(timeout)
		logs = chan.repeatLogs[key]
		trigger = self.registryValue('repeatPercent',channel=channel)
		result = False
		flag = False
		for msg in logs:
			if self._strcompare(message,msg) >= trigger:
				flag = True
				break
		if flag:
			result = self._isSomething(irc,channel,key,'repeat')
		chan.repeatLogs[key].enqueue(message)
		return result
		
	def _isMassRepeat(self,irc,channel,message):
		if self.registryValue('massRepeatPermit',channel=channel) < 0 or len(message) < self.registryValue('massRepeatChars',channel=channel):
			return False
		chan = self.getChan(irc,channel)
		life = self.registryValue('massRepeatLife',channel=channel)
		if not channel in chan.repeatLogs or chan.repeatLogs[channel].timeout != life:
			chan.repeatLogs[channel] = utils.structures.TimeoutQueue(life)
		logs = chan.repeatLogs[channel]
		trigger = self.registryValue('massRepeatPercent',channel=channel)
		result = False
		flag = False
		for msg in logs:
			if self._strcompare(message,msg) >= trigger:
				flag = True
				break
		if flag:
			result = self._isSomething(irc,channel,channel,'massRepeat')
		chan.repeatLogs[channel].enqueue(message)
		return result
	
	def _isCap(self,irc,channel,key,message):
		limit = self.registryValue('capPermit',channel=channel)
		if limit == -1:
			return False
		trigger = self.registryValue('capPercent',channel=channel)
		matchs = self.recaps.findall(message)
		if len(matchs) and len(message):
			percent = len(matchs) / len(message)
			if percent >= trigger:
				return self._isSomething(irc,channel,key,'cap')
		return False
	
	def _strcompare (self,a,b):
		# return [0 - 1] ratio between two string
		# jaccard algo
		sa, sb = set(a), set(b)
		n = len(sa.intersection(sb))
		jacc = n / float(len(sa) + len(sb) - n)
		return jacc
	
	def die(self):
		self._ircs = ircutils.IrcDict()

	def doError (self,irc,msg):
		self._ircs = ircutils.IrcDict()


Class = ChanTracker
