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
import supybot.registry as registry
import supybot.conf as conf
import socket
import re
import sqlite3
import collections
import random
from operator import itemgetter

try:
	from ipaddress import ip_address as IPAddress, ip_network as IPNetwork
except ImportError:
	try:
		from netaddr import IPAddress, IPNetwork
	except:
		print('CIDR computation is not available: netaddress or ipaddress must be installed')

#due to more kind of pattern checked, increase size

ircutils._hostmaskPatternEqualCache = utils.structures.CacheDict(4000)

cache = utils.structures.CacheDict(4000)

def applymodes(channel, args=(), prefix='', msg=None):
    """Returns a MODE that applies changes on channel."""
    modes = args
    if msg and not prefix:
        prefix = msg.prefix
    return ircmsgs.IrcMsg(prefix=prefix, command='MODE', args=[channel] + ircutils.joinModes(modes), msg=msg)

mcidr = re.compile(r'^(\d{1,3}\.){0,3}\d{1,3}/\d{1,2}$')
m6cidr = re.compile(r'^([0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}/\d{1,3}$')

def matchHostmask (pattern,n,resolve):
    # return the matched pattern for Nick
    if n.prefix == None or not ircutils.isUserHostmask(n.prefix):
        return None
    (nick,ident,host) = ircutils.splitHostmask(n.prefix)
    if '/' in host:
        if host.startswith('gateway/web/freenode/ip.'):
            n.ip = cache[n.prefix] = host.split('ip.')[1]
    try:
        if n.ip != None and '@' in pattern and mcidr.match(pattern.split('@')[1]) and IPAddress(u'%s' % n.ip) in IPNetwork(u'%s' % pattern.split('@')[1]):
            if ircutils.hostmaskPatternEqual('%s@*' % pattern.split('@')[0],'%s!%s@%s' % (nick,ident,n.ip)):
                return '%s!%s@%s' % (nick,ident,n.ip)
        if n.ip != None and '@' in pattern and m6cidr.match(pattern.split('@')[1]) and IPAddress(u'%s' % n.ip) in IPNetwork(u'%s' % pattern.split('@')[1]):
            if ircutils.hostmaskPatternEqual('%s@*' % pattern.split('@')[0],'%s!%s@%s' % (nick,ident,n.ip)):
                return '%s!%s@%s' % (nick,ident,n.ip)
    except:
        t = ''
    if ircutils.isUserHostmask(pattern):
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

def match (pattern,n,irc,resolve):
    if not pattern:
        return None
    if not n.prefix:
        return None
    # check if given pattern match an Nick
    key = pattern + ' :: ' + str(n)
    if key in cache:
        return cache[key]
    #cache[key] = None
    extprefix = ''
    extmodes = ''
    if 'extban' in irc.state.supported:
        ext = irc.state.supported['extban']
        extprefix = ext.split(',')[0]
        extmodes = ext.split(',')[1]
    if pattern.startswith(extprefix):
        p = pattern[1:]
        negate = not p[0] in extmodes
        if negate:
            p = p[1:]
        t = p[0]
        p = p[1:]
        if len(p):
            # remove ':'
            p = p[1:]
        if extprefix in p and not p.endswith(extprefix):
            # forward
            p = p[(p.rfind(extprefix)+1):]
        if t == 'a':
            cache[key] = matchAccount (pattern,p,negate,n,extprefix)
        elif t == 'r':
            cache[key] = matchRealname (pattern,p,negate,n,extprefix)
        elif t == 'x':
            cache[key] = matchGecos (pattern,p,negate,n,extprefix)
        else:
            # bug if ipv6 used ..
            k = pattern[(pattern.rfind(':')+1):]
            cache[key] = matchHostmask(k,n,resolve)
    else:
        p = pattern
        if extprefix in p:
            p = p.split(extprefix)[0]
        cache[key] = matchHostmask(p,n,resolve)
    return cache[key]

def getBestPattern (n,irc,useIp=False,resolve=True):
    # return best pattern for a given Nick
    match(n.prefix,n,irc,resolve)
    results = []
    if not n.prefix or not ircutils.isUserHostmask(n.prefix):
        return []
    (nick,ident,host) = ircutils.splitHostmask(n.prefix)
    if host.startswith('gateway/web/freenode/ip.') or host.startswith('gateway/tor-sasl/') or host.startswith('gateway/vpn/') or host.startswith('unaffiliated/') or ident.startswith('~'):
        ident = '*'
    if n.ip != None:
        if len(n.ip.split(':')) > 4:
            # large ipv6
            a = n.ip.split(':')
            m = a[0]+':'+a[1]+':'+a[2]+':'+a[3]+':*'
            results.append('*!%s@%s' % (ident,m))
        else:
            if useIp:
                results.append('*!%s@*%s' % (ident,n.ip))
            else:
                results.append('*!%s@%s' % (ident,n.ip))
    if '/' in host:
        # cloaks
        if host.startswith('gateway/'):
            if useIp and 'ip.' in host:
                ident = '*'
                host = '*%s' % host.split('ip.')[1]
            else:
                h = host.split('/')
                if 'x-' in host and not 'vpn/' in host:
                    # gateway/type/(domain|account) [?/random]
                    p = ''
                    if len(h) > 3:
                        p = '/*'
                        h = h[:3]
                        host = '%s%s' % ('/'.join(h),p)
                        (nick,i,h) = ircutils.splitHostmask(n.prefix)
        elif host.startswith('nat/'):
            h = host.replace('nat/','')
            if '/' in h:
                host = 'nat/%s/*' % h.split('/')[0]
        if 'gateway/' in host and '/x-' in host and not 'vpn/' in host:
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
    __slots__ = ('irc', 'name', 'channels', 'nicks', 'queue', 'lowQueue', 'logsSize', 'askedItems')
    # define an ircd, keeps Chan and Nick items
    def __init__(self,irc,logsSize):
        object.__init__(self)
        self.irc = irc
        self.name = irc.network
        self.channels = ircutils.IrcDict()
        self.nicks = ircutils.IrcDict()
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
            s = s + ', removed by %s' % removed_by
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

    def pending(self,irc,channel,mode,prefix,pattern,db,never,ids,duration):
        # returns active items for a channel mode
        if not channel or not mode or not prefix:
            return []
        if not ircdb.checkCapability(prefix, '%s,op' % channel):
            return []
        chan = self.getChan(irc,channel)
        results = []
        r = []
        c = db.cursor()
        t = time.time()
        for m in mode:
            items = chan.getItemsFor(m)
            if len(items):
                for item in items:
                    item = items[item]
                    if never:
                        if item.when == item.expire or not item.expire:
                            r.append([item.uid,item.mode,item.value,item.by,item.when,item.expire])
                    else:
                        if duration > 0:
                            log.debug('%s -> %s : %s' % (duration,item.when,(t-item.when)))
                            if (t - item.when) > duration:
                                r.append([item.uid,item.mode,item.value,item.by,item.when,item.expire])
                        else:
                            r.append([item.uid,item.mode,item.value,item.by,item.when,item.expire])
        r.sort(reverse=True)
        if len(r):
            for item in r:
                (uid,mode,value,by,when,expire) = item
                if pattern != None:
                    if not by.startswith(pattern):
                        if not ircutils.hostmaskPatternEqual(pattern,by):
                            continue
                c.execute("""SELECT oper, comment FROM comments WHERE ban_id=? ORDER BY at DESC LIMIT 1""",(uid,))
                L = c.fetchall()
                if len(L):
                    (oper,comment) = L[0]
                    message = ' "%s"' % comment
                else:
                    message = ''
                if ids:
                    results.append('%s' % uid)
                elif expire and expire != when:
                    results.append('[#%s +%s %s by %s expires at %s]%s' % (uid,mode,value,by,floatToGMT(expire),message))
                else:
                    results.append('[#%s +%s %s by %s on %s]%s' % (uid,mode,value,by,floatToGMT(when),message))
        c.close()
        return results

    def against (self,irc,channel,n,prefix,db,ct):
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
                    if match(item.value,n,irc,ct.registryValue('resolveIp')):
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

    def search (self,irc,pattern,prefix,db,deep,active,never,channel,ids):
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
        if deep:
            c.execute("""SELECT ban_id, full FROM nicks WHERE full GLOB ? OR full LIKE ? OR log GLOB ? OR log LIKE ? ORDER BY ban_id DESC""",(glob,like,glob,like))
        else:
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
                c.execute("""SELECT id, mask, kind, channel, begin_at, end_at, removed_at FROM bans WHERE id=? ORDER BY id DESC LIMIT 1""",(uid,))
                items = c.fetchall()
                for item in items:
                    (uid,mask,kind,chan,begin_at,end_at,removed_at) = item
                    if isOwner or ircdb.checkCapability(prefix, '%s,op' % chan):
                        if never or active:
                            if removed_at:
                                continue
                        if never:
                            if begin_at != end_at:
                                continue
                        if channel and len(channel):
                            if chan != channel:
                                continue
                        results.append([uid,mask,kind,chan])
        if len(results):
            results.sort(reverse=True)
            i = 0
            msgs = []
            while i < len(results):
                (uid,mask,kind,chan) = results[i]
                if ids:
                    msgs.append('%s' % uid)
                elif channel and len(channel):
                    msgs.append('[#%s +%s %s]' % (uid,kind,mask))
                else:
                    msgs.append('[#%s +%s %s in %s]' % (uid,kind,mask,chan))
                i = i+1
            c.close()
            return msgs
        c.close()
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
            if prefix != irc.prefix and ct.registryValue('announceMark',channel=channel):
                f = ct._logChan
            elif prefix == irc.prefix and ct.registryValue('announceBotMark',channel=channel):
                f = ct._logChan
            if f:
                if ct.registryValue('useColorForAnnounces',channel=channel):
                    f(irc,channel,'[%s] [#%s %s %s] marked by %s: %s' % (ircutils.bold(channel),ircutils.mircColor(uid,'yellow','black'),ircutils.bold(ircutils.mircColor('+%s' % kind,'red')),ircutils.mircColor(mask,'light blue'),prefix.split('!')[0],message))
                else:
                    f(irc,channel,'[%s] [#%s +%s %s] marked by %s: %s' % (channel,uid,kind,mask,prefix.split('!')[0],message))
            b = True
        c.close()
        return b

    def mark (self,irc,uid,message,prefix,db,logFunction,ct):
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
                if ct.registryValue('useColorForAnnounces',channel=channel):
                    logFunction(irc,channel,'[%s] [#%s %s %s] marked by %s: %s' % (ircutils.bold(channel),ircutils.mircColor(uid,'yellow','black'),ircutils.bold(ircutils.mircColor('+%s' % kind,'red')),ircutils.mircColor(mask,'light blue'),prefix.split('!')[0],message))
                else:
                    logFunction(irc,channel,'[%s] [#%s +%s %s] marked by %s: %s' % (channel,uid,kind,mask,prefix.split('!')[0],message))
            b = True
        c.close()
        return b

    def submark (self,irc,channel,mode,value,message,prefix,db,logFunction,ct):
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
            return self.mark(irc,uid,message,prefix,db,logFunction,ct)
        else:
            c.close()
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
            (id,oper) = L[0]
            c.close()
            if channel in self.channels:
                chan = self.getChan(irc,channel)
                hash = '%s%s' % (mode,value)
                chan.update[hash] = [mode,value,seconds,prefix]
                return True
            return False
        else:
            c.close()
            if channel in self.channels:
                chan = self.getChan(irc,channel)
                hash = '%s%s' % (mode,value)
                # prepare item update after being set ( we don't have id yet )
                chan.update[hash] = [mode,value,seconds,prefix]
                # enqueue mode changes
                chan.queue.enqueue(('+%s' % mode,value))
                return True
        return False

    def edit (self,irc,channel,mode,value,seconds,prefix,db,scheduleFunction,logFunction,ct):
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
            if begin_at == end_at and seconds < 0:
                c.close()
                return True
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
                if ct.registryValue('useColorForAnnounces',channel=channel):
                    logFunction(irc,channel,'[%s] [#%s %s %s] edited by %s: %s' % (ircutils.bold(channel),ircutils.mircColor(str(uid),'yellow','black'),ircutils.bold(ircutils.mircColor('+%s' % kind,'red')),ircutils.mircColor(mask,'light blue'),prefix.split('!')[0],reason))
                else:
                    logFunction(irc,channel,'[%s] [#%s +%s %s] edited by %s: %s' % (channel,uid,kind,mask,prefix.split('!')[0],reason))
            b = True
        c.close()
        return b

    def resync (self,irc,channel,mode,db,logFunction,ct):
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
                            if ct.registryValue('useColorForAnnounces',channel=channel):
                                msgs.append('[#%s %s]' % (ircutils.mircColor(uid,'yellow','black'),ircutils.mircColor(mask,'light blue')))
                            else:
                                msgs.append('[#%s %s]' % (uid,mask))
        if commits > 0:
            db.commit()
            if logFunction:
                if ct.registryValue('useColorForAnnounces',channel=channel):
                    logFunction(irc,channel,'[%s] [%s] %s removed: %s' % (ircutils.bold(channel),ircutils.mircColor(mode,'green'),commits, ' '.join(msgs)))
                else:
                    logFunction(irc,channel,'[%s] [%s] %s removed: %s' % (channel,mode,commits, ' '.join(msgs)))
        # todo restore patterns
        c.execute("""SELECT id, pattern, regexp, trigger, life, mode, duration FROM patterns WHERE channel=? ORDER BY id""",(channel,))
        L = c.fetchall()
        if len(L):
            if channel in irc.state.channels:
                chan = self.getChan(irc,channel)
                for record in L:
                    (uid, pattern, regexp, trigger, life, mode, duration) = record
                    chan.patterns[uid] = Pattern(uid,pattern,int(regexp) == 1, trigger, life, mode, duration)
        c.close()

class Chan (object):
    __slots__ = ('ircd', 'name', '_lists', 'queue', 'update', 'mark', 'action', 'dones', 'syn', 'opAsked', 'deopAsked', 'deopPending', 'spam', 'repeatLogs', 'nicks', 'netsplit', 'attacked', 'patterns')
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
        self.netsplit = False
        self.attacked = False
        self.patterns = {}

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

    def summary (self,db):
        r = []
        c = db.cursor()
        c.execute("""SELECT id,oper,kind,removed_at FROM bans WHERE channel=?""",(self.name,))
        L = c.fetchall()
        total = {}
        opers = {}
        if len(L):
            for item in L:
                (id,oper,kind,removed_at) = item
                if not kind in total:
                    total[kind] = {}
                    total[kind]['active'] = 0
                    total[kind]['removed'] = 0
                if not removed_at:
                    total[kind]['active'] = total[kind]['active'] + 1
                else:
                    total[kind]['removed'] = total[kind]['removed'] + 1
                if not oper in opers:
                    opers[oper] = {}
                if not kind in opers[oper]:
                    opers[oper][kind] = {}
                    opers[oper][kind]['active'] = 0
                    opers[oper][kind]['removed'] = 0
                if not removed_at:
                    opers[oper][kind]['active'] = opers[oper][kind]['active'] + 1
                else:
                    opers[oper][kind]['removed'] = opers[oper][kind]['removed'] + 1
            for kind in total:
                r.append('+%s: %s/%s (active/total)' % (kind,total[kind]['active'],total[kind]['active']+total[kind]['removed']))
            for oper in opers:
                r.append('%s:' % oper)
                for kind in opers[oper]:
                    r.append('+%s: %s/%s (active/total)' % (kind,opers[oper][kind]['active'],opers[oper][kind]['active']+opers[oper][kind]['removed']))
        c.close()
        return r

    def addItem (self,mode,value,by,when,db,checkUser=True,ct=None):
        # eqIb(+*) (-ov) pattern prefix when
        # mode : eqIb -ov + ?
        if mode != 'm':
            l = self.getItemsFor(mode)
        else:
            l = {}
        if not self.syn:
            checkUser = False
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
                i.isNew = False
                if len(L):
                    for item in L:
                        (uid,full) = item
                        i.affects.append(full)
            else:
                # if begin_at == end_at --> that means forever
                c.execute("""INSERT INTO bans VALUES (NULL, ?, ?, ?, ?, ?, ?,NULL, NULL)""", (self.name,by,mode,value,when,when))
                i.isNew = True
                uid = c.lastrowid
                # leave channel's users list management to supybot
                ns = []
                if self.name in self.ircd.irc.state.channels and checkUser:
                    L = []
                    for nick in list(self.ircd.irc.state.channels[self.name].users):
                        L.append(nick)
                    for nick in L:
                        n = self.ircd.getNick(self.ircd.irc,nick)
                        m = match(value,n,self.ircd.irc,ct.registryValue('resolveIp'))
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
        else:
            l[value].isNew = False
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
                i.channel = self.name
                i.by = by
                i.when = float(when)
                i.expire = float(expire)
        if i:
            c.execute("""UPDATE bans SET removed_at=?, removed_by=? WHERE id=?""", (removed_at,by,int(i.uid)))
            i.removed_by = by
            i.removed_at = removed_at
            self._lists[mode].pop(value)
        return i

    def addpattern (self,prefix,limit,life,mode,duration,pattern,regexp,db):
        if not ircdb.checkCapability(prefix,'%s,op' % self.name):
            if prefix != irc.prefix:
                return False
        c = db.cursor()
        c.execute("""INSERT INTO patterns VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""", (self.name,prefix,time.time(),pattern,regexp,limit,life,mode,duration))
        uid = c.lastrowid
        self.patterns[uid] = Pattern(uid,pattern,regexp == 1,limit,life,mode,duration)
        db.commit()
        c.close()
        r = ''
        if regexp == 1:
            r = ' *'
        return '[#%s "%s"%s]' % (uid,pattern,r)

    def rmpattern (self,prefix,uid,db):
        if not ircdb.checkCapability(prefix,'%s,op' % self.name):
            if prefix != irc.prefix:
                return False
        c = db.cursor()
        uid = int(uid)
        c.execute("""SELECT id, channel, pattern, regexp FROM patterns WHERE id=? and channel=? LIMIT 1""",(uid,self.name))
        items = c.fetchall()
        if len(items):
            (id,channel,pattern,regexp) = items[0]
            c.execute("""DELETE FROM patterns WHERE id=? and channel=? LIMIT 1""",(uid,self.name))
            if uid in self.patterns:
                del self.patterns[uid]
            prop = 'Pattern%s' % id
            if prop in self.spam:
                del self.spam[prop]
            db.commit()
            c.close()
            r = ''
            if regexp == 1:
                r = ' *'
            return '[#%s "%s"%s]' % (uid,pattern,r)
        c.close()
        return False

    def countpattern (self,uid,db):
        c = db.cursor()
        c.execute("""SELECT id, count FROM patterns WHERE id=? and channel=? LIMIT 1""",(uid,self.name))
        items = c.fetchall()
        (id, count) = items[0]
        c.execute("""UPDATE patterns SET count=? WHERE id=?""", (int(count)+1,int(uid)))
        db.commit()
        c.close()

    def lspattern (self,prefix,pattern,db):
        if not ircdb.checkCapability(prefix,'%s,op' % self.name):
            if prefix != irc.prefix:
                return []
        c = db.cursor()
        results = []
        items = []
        if pattern:
            i = None
            try:
                i = int(pattern)
            except:
                i = None
            if i:
                c.execute("""SELECT id, channel, pattern, oper, at, trigger, life, mode, duration, count, regexp FROM patterns WHERE id=? AND channel=? LIMIT 1""",(i,self.name))
                items = c.fetchall()
                if len(items):
                    (uid,channel,pattern,oper,at,limit,life,mode,duration,count, regexp) = items[0]
                    r = ''
                    if regexp == 1:
                        r = ' *'
                    results.append('[#%s by %s on %s (%s calls) %s/%ss -> %s for %ss: "%s"%s]' % (uid,oper,floatToGMT(at),count,limit,life,mode,duration,pattern,r))
                    items = []
            else:
                glob = '*%s*' % pattern
                like = '%'+pattern+'%'
                c.execute("""SELECT id, channel, pattern, oper, at, trigger, life, mode, duration, count, regexp FROM patterns WHERE (pattern GLOB ? or pattern LIKE ?) AND channel=? ORDER BY id DESC""",(glob,like,self.name))
                items = c.fetchall()
        else:
            c.execute("""SELECT id, channel, pattern, oper, at, trigger, life, mode, duration, count, regexp FROM patterns WHERE channel=? ORDER BY id DESC""",(self.name,))
            items = c.fetchall()
        if len(items):
            for item in items:
                (uid,channel,pattern,oper,at,limit,life,mode,duration,count, regexp) = item
                r = ''
                if regexp == 1:
                    r = ' *'
                results.append('[#%s (%s calls) %s/%ss -> %s for %ss: "%s"%s]' % (uid,count,limit,life,mode,duration,pattern,r))
        return results

class Item (object):
    __slots__ = ('channel', 'mode', 'value', 'by', 'when', 'uid', 'expire', 'removed_at', 'removed_by', 'asked', 'affects', 'isNew')
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
        self.isNew = False

    def __repr__(self):
        end = self.expire
        if self.when == self.expire:
            end = None
        return 'Item(%s [%s][%s] by %s on %s, expire on %s, removed on %s by %s)' % (self.uid,self.mode,self.value,self.by,floatToGMT(self.when),floatToGMT(end),floatToGMT(self.removed_at),self.removed_by)

class Nick (object):
    __slots__ = ('prefix', 'ip', 'realname', 'account', 'logSize', 'logs')
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
        if self.prefix != prefix:
            self.ip = None
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

class Pattern (object):
    __slots__ = ('uid', 'pattern', 'regexp', 'limit', 'life', 'mode', 'duration','_match')
    def __init__(self, uid, pattern, regexp, limit, life, mode, duration):
        self.uid = uid
        self.pattern = pattern
        self.limit = limit
        self.life = life
        self.mode = mode
        self.duration = duration
        self._match = False
        if regexp:
            self._match = utils.str.perlReToPythonRe(pattern)

    def match (self, text):
        if self._match:
            return self._match.search (text) != None
        return self.pattern in text

def _getRe(f):
    def get(irc, msg, args, state):
        original = args[:]
        s = args.pop(0)
        def isRe(s):
            try:
                foo = f(s)
                return True
            except ValueError:
                return False
        try:
            while len(s) < 512 and not isRe(s):
                s += ' ' + args.pop(0)
            if len(s) < 512:
                state.args.append([s,f(s)])
            else:
                state.errorInvalid('regular expression', s)
        except IndexError:
            args[:] = original
            state.errorInvalid('regular expression', s)
    return get

getPatternAndMatcher = _getRe(utils.str.perlReToPythonRe)

addConverter('getPatternAndMatcher', getPatternAndMatcher)


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
        elif kind == '-':
               state.args.append(float(seconds))
               raise callbacks.ArgumentError
        args.pop(0)
    state.args.append(float(seconds))

addConverter('getTs', getTs)

import threading
import supybot.world as world

def getDuration (seconds):
    if not len(seconds):
        return -1
    return seconds[0]

def getWrapper(name):
    parts = registry.split(name)
    group = getattr(conf, parts.pop(0))
    while parts:
        try:
            group = group.get(parts.pop(0))
        except (registry.NonExistentRegistryEntry,
                registry.InvalidRegistryName):
            raise registry.InvalidRegistryName(name)
    return group

def listGroup(group):
    L = []
    for (vname, v) in group._children.iteritems():
        if hasattr(group, 'channelValue') and group.channelValue and \
            ircutils.isChannel(vname) and not v._children:
            continue
        if hasattr(v, 'channelValue') and v.channelValue:
            L.append(vname)
        utils.sortBy(str.lower, L)
    return L

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
        self.dbUpgraded = False
        self.forceTickle = True
        self._ircs = ircutils.IrcDict()
        self.getIrc(irc)
        self.recaps = re.compile("[A-Z]")
        self.starting = world.starting
        if self.registryValue('announceNagInterval') > 0:
            schedule.addEvent(self.checkNag,time.time()+self.registryValue('announceNagInterval'))

    def checkNag (self):
        if world:
            if world.ircs:
                for irc in world.ircs:
                    for channel in irc.state.channels:
                        if self.registryValue('logChannel',channel=channel) in irc.state.channels:
                            toNag = ''
                            for mode in self.registryValue('announceNagMode',channel=channel):
                                if mode in irc.state.channels[channel].modes:
                                    toNag = mode
                                    break
                            if len(toNag):
                                message = '[%s] has %s mode' % (channel,toNag)
                                if self.registryValue('useColorForAnnounces',channel=channel):
                                    message = '[%s] has %s mode' % (ircutils.bold(channel),toNag)
                                self._logChan(irc,channel,message)
        if self.registryValue('announceNagInterval') > 0:
            schedule.addEvent(self.checkNag,time.time()+self.registryValue('announceNagInterval'))

    def summary (self,irc,msg,args,channel):
        """[<channel>]

        returns various statistics about channel activity"""
        c = self.getChan(irc,channel)
        messages = c.summary(self.getDb(irc.network))
        for message in messages:
            irc.queueMsg(ircmsgs.privmsg(msg.nick,message))
        irc.replySuccess()
    summary = wrap(summary,['op','channel'])

    def extract (self,irc,msg,args,channel,newChannel):
        """[<channel>] [<newChannel>]

        returns a snapshot of ChanTracker's settings for the given <channel>, if <newChannel> provided, settings are copied"""
        namespace = 'supybot.plugins.ChanTracker'
        group = getWrapper(namespace)
        L = listGroup(group)
        msgs = []
        props = []
        for prop in L:
            p = getWrapper('%s.%s' % (namespace,prop))
            if p.channelValue:
                value = str(p) or ''
                channelValue = str(p.get(channel))
                if value != channelValue:
                    props.append([prop,channelValue])
                    msgs.append(ircmsgs.privmsg(msg.nick,'config channel %s %s.%s %s' % (channel,namespace,prop,channelValue)))
        if len(msgs):
            if newChannel:
                for prop in props:
                    newChan = getWrapper('%s.%s.%s' % (namespace,prop[0],newChannel))
                    newChan.set(prop[1])
            else:
                for m in msgs:
                    irc.queueMsg(m)
            irc.replySuccess()
        else:
            irc.reply("%s uses global's settings" % channel)
    extract = wrap(extract,['owner','private','channel',optional('validChannel')])

    def editandmark (self,irc,msg,args,user,ids,seconds,reason):
        """<id>[,<id>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1s> means forever, <0s> means remove] [<reason>]

        change expiration and mark of an active mode change, if you got this message while the bot prompted you, your changes were not saved"""
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
                be = i.edit(irc,item.channel,item.mode,item.value,getDuration(seconds),msg.prefix,self.getDb(irc.network),self._schedule,f,self)
                f = None
                if self.registryValue('announceMark',channel=item.channel):
                    f = self._logChan
                if be:
                    if reason and len(reason):
                        bm = i.mark(irc,id,reason,msg.prefix,self.getDb(irc.network),f,self)
                    else:
                        bm = True
                b = b and be and bm
            else:
                b = False
        if b:
            irc.replySuccess()
        else:
            irc.reply('item not found, already removed or not enough rights to modify it')
        self.forceTickle = True
    editandmark = wrap(editandmark,['user',commalist('int'),any('getTs',True),optional('text')])

    def edit (self,irc,msg,args,user,ids,seconds):
        """<id> [,<id>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1s>] means forever

        change expiration of some active modes"""
        i = self.getIrc(irc)
        b = True
        sf = None
        if not len(ids) > 1:
            sf = self._schedule
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
                b = b and i.edit(irc,item.channel,item.mode,item.value,getDuration(seconds),msg.prefix,self.getDb(irc.network),sf,f,self)
            else:
                b = False;
        if not sf and getDuration(seconds) > 0:
            self._schedule(irc,float(time.time())+getDuration(seconds))
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
            irc.replies(results,None,None,False)
        else:
            irc.reply('item not found or not enough rights to see detail')
        self._tickle(irc)
    detail = wrap(detail,['user','int'])

    def affect (self,irc,msg,args,user,uid):
        """<id>

        list users affected by a mode change"""
        i = self.getIrc(irc)
        results = i.affect (irc,uid,msg.prefix,self.getDb(irc.network))
        if len(results):
            irc.replies(results,None,None,False)
        else:
            irc.reply('item not found or not enough rights to see affected users')
        self._tickle(irc)
    affect = wrap(affect, ['user','int'])

    def mark(self,irc,msg,args,user,ids,message):
        """<id> [,<id>] <message>

        add comment on a mode change"""
        i = self.getIrc(irc)
        b = True
        for id in ids:
            item = i.getItem(irc,id)
            if item:
                f = None
                if msg.prefix != irc.prefix and self.registryValue('announceMark',channel=item.channel):
                    f = self._logChan
                elif msg.prefix == irc.prefix and self.registryValue('announceBotMark',channel=item.channel):
                    f = self._logChan
                b = b and i.mark(irc,id,message,msg.prefix,self.getDb(irc.network),f,self)
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

    def query (self,irc,msg,args,user,optlist,text):
        """[--deep] [--never] [--active] [--ids] [--channel=<channel>] <pattern|hostmask|comment>

        search inside ban database, --deep to search on log, --never returns items set forever and active,
        --active returns only active modes, --ids returns only ids, --channel reduces results to a specific channel"""
        i = self.getIrc(irc)
        deep = False
        never = False
        active = False
        channel = None
        ids = False
        for (option, arg) in optlist:
            if option == 'deep':
                deep = True
            elif option == 'never':
                never = True
            elif option == 'active':
                active = True
            elif option == 'channel':
                channel = arg
            elif option == 'ids':
                ids = True
        if never:
            active = True
        results = i.search(irc,text,msg.prefix,self.getDb(irc.network),deep,active,never,channel,ids)
        if len(results):
            irc.replies(results,None,None,False)
        else:
            irc.reply('nothing found')
    query = wrap(query,['user',getopts({'deep': '', 'never': '', 'ids':'', 'active' : '','channel':'channel'}),'text'])

    def pending (self, irc, msg, args, channel, optlist):
        """[<channel>] [--mode=<e|b|q|l>] [--oper=<nick|hostmask>] [--never] [--ids] [--duration [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s]]

        returns active items for --mode, filtered by --oper, --never (never expire), --ids (only ids), --duration (item longer than)"""
        mode = None
        oper = None
        never = False
        ids = False
        duration = -1
        for (option, arg) in optlist:
            if option == 'mode':
                mode = arg
            elif option == 'oper':
                oper = arg
            elif option == 'never':
                never = True
            elif option == 'ids':
                ids = True
            elif option == 'duration':
                duration = int(arg)
        if never and duration > 0:
            irc.reply("you can't use --never and --duration at same time")
            return
        i = self.getIrc(irc)
        if oper in i.nicks:
            oper = self.getNick(irc,oper).prefix
        results = []
        if not mode:
            mode = self.registryValue('modesToAskWhenOpped',channel=channel) + self.registryValue('modesToAsk',channel=channel)
        results = i.pending(irc,channel,mode,msg.prefix,oper,self.getDb(irc.network),never,ids,duration)
        if len(results):
            irc.reply(', '.join(results), private=True)
        else:
            irc.reply('no result')
    pending = wrap(pending,['op',getopts({'mode': 'letter', 'never': '', 'oper' : 'somethingWithoutSpaces', 'ids' : '', 'duration' : 'getTs'})])

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
            return applymodes(channel,L)
        self._modes(irc.state.supported.get('modes', 1),self.getChan(irc,channel),ircutils.separateModes(modes),f)
        self.forceTickle = True
        self._tickle(irc)
    modes = wrap(modes, ['op', many('something')])

    def do (self,irc,msg,args,channel,mode,items,seconds,reason):
        """[<channel>] <mode> <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1> or empty means forever] <reason>

        +<mode> targets for duration <reason> is mandatory"""
        if mode in self.registryValue('modesToAsk',channel=channel) or mode in self.registryValue('modesToAskWhenOpped',channel=channel):
            b = self._adds(irc,msg,args,channel,mode,items,getDuration(seconds),reason,False)
            if not msg.nick == irc.nick and not b:
                irc.reply('unknown pattern or pattern already active')
        else:
            irc.reply('selected mode is not supported by config, see modesToAsk and modesToAskWhenOpped')

    do = wrap(do,['op','letter',commalist('something'),any('getTs',True),rest('text')])

    def q (self,irc,msg,args,channel,items,seconds,reason):
        """[<channel>] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1> or empty means forever] <reason>

        +q targets for duration <reason> is mandatory"""
        b = self._adds(irc,msg,args,channel,'q',items,getDuration(seconds),reason,False)
        if not msg.nick == irc.nick and not b:
            irc.reply('unknown pattern, or pattern already active')
    q = wrap(q,['op',commalist('something'),any('getTs',True),rest('text')])

    def b (self, irc, msg, args, channel, optlist, items, seconds, reason):
        """[<channel>] [--perm] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1> or empty means forever] <reason>

        +b targets for duration <reason> is mandatory, add --perm if you want to add it to permanent bans of Channel"""
        perm = False
        for (option, arg) in optlist:
            if option == 'perm':
                perm = True
        b = self._adds(irc,msg,args,channel,'b',items,getDuration(seconds),reason,perm)
        if not msg.nick == irc.nick and not b:
            irc.reply('unknown pattern, or pattern already active')
    b = wrap(b,['op',getopts({'perm':''}),commalist('something'),any('getTs',True),rest('text')])

    def i (self, irc, msg, args, channel, items, seconds, reason):
        """[<channel>] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1> or empty means forever] <reason>

        +I targets for duration <reason> is mandatory"""
        b = self._adds(irc,msg,args,channel,'I',items,getDuration(seconds),reason,False)
        if not msg.nick == irc.nick and not b:
            irc.reply('unknown pattern, or pattern already active')
    i = wrap(i,['op',commalist('something'),any('getTs',True),rest('text')])

    def e (self, irc, msg, args, channel, items, seconds, reason):
        """[<channel>] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1> or empty means forever] <reason>

        +e targets for duration <reason> is mandatory"""
        b = self._adds(irc,msg,args,channel,'e',items,getDuration(seconds),reason,False)
        if not msg.nick == irc.nick and not b:
            irc.reply('unknown pattern, or pattern already active')
    e = wrap(e,['op',commalist('something'),any('getTs',True),rest('text')])

    def undo (self, irc, msg, args, channel, mode, items):
        """[<channel>] <mode> <nick|hostmask|*> [<nick|hostmask|*>]

        sets -<mode> on them, if * found, remove them all"""
        b = self._removes(irc,msg,args,channel,mode,items,False)
        if not msg.nick == irc.nick and not b:
            irc.reply('unknown patterns, already removed or unsupported mode')
    undo = wrap(undo,['op','letter',many('something')])

    def uq (self, irc, msg, args, channel, items):
        """[<channel>] <nick|hostmask|*> [<nick|hostmask|*>]

        sets -q on them, if * found, remove them all"""
        b = self._removes(irc,msg,args,channel,'q',items,False)
        if not msg.nick == irc.nick and not b:
            irc.reply('unknown patterns, already removed or unsupported mode')
    uq = wrap(uq,['op',many('something')])

    def ub (self, irc, msg, args, channel, optlist, items):
        """[<channel>] [--perm] <nick|hostmask|*> [<nick|hostmask>]

        sets -b on them, if * found, remove them all, --perm to remove them for permanent bans"""
        perm = False
        for (option, arg) in optlist:
            if option == 'perm':
                perm = True
        b = self._removes(irc,msg,args,channel,'b',items,perm)
        if not msg.nick == irc.nick and not b:
            if perm:
                if len(items) == 1:
                    irc.reply('unknown patterns or already removed, you may try "channel ban remove %s %s"' % (channel,items[0]))
                else:
                    irc.reply('unknown patterns or already removed, you may try "channel ban remove %s %s"' % (channel,''))
            else:
                irc.reply('unknown patterns, already removed or unsupported mode')
    ub = wrap(ub,['op',getopts({'perm':''}),many('something')])

    def ui (self, irc, msg, args, channel, items):
        """[<channel>] <nick|hostmask|*> [<nick|hostmask|*>]

        sets -I on them, if * found, remove them all"""
        b = self._removes(irc,msg,args,channel,'I',items,False)
        if not msg.nick == irc.nick and not b:
            irc.reply('unknown patterns, already removed or unsupported mode')
    ui = wrap(ui,['op',many('something')])

    def ue (self, irc, msg, args, channel, items):
        """[<channel>] <nick|hostmask|*> [<nick|hostmask|*>]

        sets -e on them, if * found, remove them all"""
        b = self._removes(irc,msg,args,channel,'e',items,False)
        if not msg.nick == irc.nick and not b:
            irc.reply('unknown patterns, already removed or unsupported mode')
    ue = wrap(ue,['op',many('something')])

    def r (self,irc,msg,args,channel,nick,reason):
        """[<channel>] <nick> [<reason>]

        force a part on <nick> with <reason> if provided"""
        chan = self.getChan(irc,channel)
        if not reason:
            reason = msg.nick
        chan.action.enqueue(ircmsgs.IrcMsg('REMOVE %s %s :%s' % (channel,nick,reason)))
        self.forceTickle = True
        self._tickle(irc)
    r = wrap(r,['op','nickInChannel',additional('text')])

    def k (self,irc,msg,args,channel,nick,reason):
        """[<channel>] <nick> [<reason>]

        kick <nick> with <reason> if provided"""
        chan = self.getChan(irc,channel)
        if not reason:
            reason = msg.nick
        chan.action.enqueue(ircmsgs.kick(channel,nick,reason))
        self.forceTickle = True
        self._tickle(irc)
    k = wrap(k,['op','nickInChannel',additional('text')])

    def overlap (self,irc,msg,args,channel,mode):
        """[<channel>] <mode>

        returns overlapping modes, there is limitation with extended bans"""
        results = []
        if mode in self.registryValue('modesToAsk',channel=channel) or mode in self.registryValue('modesToAskWhenOpped',channel=channel):
            chan = self.getChan(irc,channel)
            modes = chan.getItemsFor(self.getIrcdMode(irc,mode,'*!*@*')[0])
            if len(modes):
                L = []
                for m in modes:
                    L.append(modes[m])
                if len(L) > 1:
                    item = L.pop()
                    while len(L):
                        for i in L:
                            if ircutils.isUserHostmask(i.value):
                                n = Nick(0)
                                n.setPrefix(i.value)
                                if match(item.value,n,irc,self.registryValue('resolveIp')):
                                    results.append('[#%s %s] matches [#%s %s]' % (item.uid,item.value,i.uid,i.value))
                        item = L.pop()
        if len(results):
            irc.reply(' '.join(results), private=True)
        else:
            irc.reply('no results, or unknown mode')
        self._tickle(irc)
    overlap = wrap(overlap,['op','text'])

    def match (self,irc,msg,args,channel,prefix):
        """[<channel>] <nick|hostmask#username>

        returns active mode that targets nick given, nick must be in a channel shared with the bot"""
        i = self.getIrc(irc)
        n = None
        if prefix in i.nicks:
            n = self.getNick(irc,prefix)
        else:
            if ircutils.isUserHostmask(prefix):
                n = Nick(0)
                if '#' in prefix:
                    a = prefix.split('#')
                    username = a[1]
                    prefix = a[0]
                    n.setPrefix(prefix)
                    n.setRealname(username)
                else:
                    n.setPrefix(prefix)
            else:
                irc.reply('unknow nick')
                return
        results = i.against(irc,channel,n,msg.prefix,self.getDb(irc.network),self)
        if len(results):
            irc.reply(' '.join(results), private=True)
        else:
            irc.reply('no results')
        self._tickle(irc)
    match = wrap(match,['op','text'])

    def check (self,irc,msg,args,channel,pattern):
        """[<channel>] <pattern>

        returns a list of affected users by a pattern"""
        if ircutils.isUserHostmask(pattern) or self.getIrcdExtbansPrefix(irc) in pattern:
            results = []
            i = self.getIrc(irc)
            for nick in list(irc.state.channels[channel].users):
                if nick in i.nicks:
                    n = self.getNick(irc,nick)
                    m = match(pattern,n,irc,self.registryValue('resolveIp'))
                    if m:
                        results.append('[%s - %s]' % (nick,m))
            if len(results):
                irc.reply('%s user(s): %s' % (len(results),' '.join(results)))
            else:
                irc.reply('nobody will be affected')
        else:
            irc.reply('invalid pattern given')
    check = wrap (check,['op','text'])

    def getmask (self,irc,msg,args,channel,prefix):
        """[<channel>] <nick|hostmask>

        returns a list of hostmask's pattern, best first, mostly used for debug"""
        i = self.getIrc(irc)
        if prefix in i.nicks:
            irc.reply(' '.join(getBestPattern(self.getNick(irc,prefix),irc,self.registryValue('useIpForGateway',channel=channel),self.registryValue('resolveIp'))))
        else:
            n = Nick(0)
            #gecos ( $x )
            if '#' in prefix:
                a = prefix.split('#')
                username = a[1]
                prefix = a[0]
                n.setPrefix(prefix)
                n.setRealname(username)
            else:
                n.setPrefix(prefix)
            if ircutils.isUserHostmask(prefix):
                irc.reply(' '.join(getBestPattern(n,irc,self.registryValue('useIpForGateway',channel=channel),self.registryValue('resolveIp'))))
                return
            irc.reply('nick not found or wrong hostmask given')
    getmask = wrap(getmask,['op','text'])

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
            irc.reply(chan.isWrong(getBestPattern(self.getNick(irc,nick),irc,self.registryValue('useIpForGateway',channel=channel),self.registryValue('resolveIp'))[0]))
        else:
            irc.reply('nick not found')
    isbad = wrap(isbad,['op','nick'])

    def vacuum (self,irc,msg,args):
        """VACUUM the database"""
        db = self.getDb(irc.network)
        c = db.cursor()
        c.execute('VACUUM')
        c.close()
        irc.replySuccess()
    vacuum = wrap(vacuum,['owner'])

    def note (self,irc,msg,args,channel,items,reason):
        """[<channel>] <nick|hostmask>[,<nick|hostmask>] <reason>

        store a new item in database under the mode 'm', markeable but not editable"""
        i = self.getIrc(irc)
        targets = []
        chan = self.getChan(irc,channel)
        for item in items:
            if item in chan.nicks or item in irc.state.channels[channel].users:
                n = self.getNick(irc,item)
                patterns = getBestPattern(n,irc,self.registryValue('useIpForGateway',channel=channel),self.registryValue('resolveIp'))
                if len(patterns):
                    targets.append(patterns[0])
            elif ircutils.isUserHostmask(item) or self.getIrcdExtbansPrefix(irc) in item:
                targets.append(item)
        for target in targets:
            item = chan.addItem ('m',target,msg.prefix,time.time(),self.getDb(irc.network),self.registryValue('doActionAgainstAffected',channel=channel),self)
            f = None
            if msg.prefix != irc.prefix and self.registryValue('announceMark',channel=channel):
                f = self._logChan
            db = self.getDb(irc.network)
            c = db.cursor()
            c.execute("""UPDATE bans SET removed_at=?, removed_by=? WHERE id=?""", (time.time()+1,msg.prefix,int(item.uid)))
            db.commit()
            c.close()
            i.mark(irc,item.uid,reason,msg.prefix,self.getDb(irc.network),f,self)
        if not msg.nick == irc.nick:
            if len(targets):
                irc.replySuccess()
            else:
                irc.reply('unknown patterns')
    note = wrap(note,['op',commalist('something'),rest('text')])

    def addpattern (self, irc, msg, args, channel, limit, life, mode, duration, pattern):
        """[<channel>] <limit> <life> <mode>(bqeId) [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] <pattern>

        add a <pattern> which triggers <mode> for <duration> if the <pattern> appears more than <limit> (0 for immediate action) during <life> in seconds"""
        chan = self.getChan(irc,channel)
        result = chan.addpattern(msg.prefix,limit,life,mode,getDuration(duration),pattern,0,self.getDb(irc.network))
        if result:
            irc.reply(result)
        else:
            irc.reply('not enough rights to add a pattern on %s' % channel)
    addpattern = wrap (addpattern,['op','nonNegativeInt','positiveInt', 'letter', any('getTs',True), rest('text')])


    def addregexpattern (self, irc, msg, args, channel, limit, life, mode, duration, pattern):
        """[<channel>] <limit> <life> <mode>(bqeId) [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] /<pattern>/

        add a <pattern> which triggers <mode> for <duration> if the <pattern> appears more than <limit> (0 for immediate action) during <life> in seconds"""
        chan = self.getChan(irc,channel)
        result = chan.addpattern(msg.prefix,limit,life,mode,getDuration(duration),pattern[0],1,self.getDb(irc.network))
        if result:
            irc.reply(result)
        else:
            irc.reply('not enough rights to add a pattern on %s' % channel)
    addregexpattern = wrap (addregexpattern,['op','nonNegativeInt','positiveInt', 'letter', any('getTs',True), rest('getPatternAndMatcher')])

    def rmpattern (self, irc, msg, args, channel, ids):
        """[<channel>] <id> [<id>]

        remove patterns by <id>"""
        results = []
        chan = self.getChan(irc,channel)
        for id in ids:
            result = chan.rmpattern(msg.prefix,id,self.getDb(irc.network))
            if result:
                results.append(result)
        if len(results):
            irc.reply('%s removed: %s' % (len(results),','.join(results)))
        else:
            irc.reply('not found or not enough rights')
    rmpattern = wrap(rmpattern,['op',many('positiveInt')])

    def lspattern (self, irc, msg, args, channel, pattern):
        """[<channel>] [<id|pattern>]

        return patterns in <channel> filtered by optional <pattern>"""
        results = []
        chan = self.getChan(irc,channel)
        results = chan.lspattern(msg.prefix,pattern,self.getDb(irc.network))
        if len (results):
            irc.replies(results,None,None,False)
        else:
            irc.reply('nothing found')
    lspattern = wrap(lspattern,['op',optional('text')])

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
                        mode = 'b'
                        if pattern and not pattern.startswith('m:'):
                            pattern = prefix + 'm' + ':' + pattern
        return [mode,pattern]

    def getIrcdExtbansPrefix (self,irc):
        if 'extban' in irc.state.supported:
            return irc.state.supported['extban'].split(',')[0]
        return ''

    def _adds (self,irc,msg,args,channel,mode,items,duration,reason,perm):
        i = self.getIrc(irc)
        targets = []
        if mode in self.registryValue('modesToAsk',channel=channel) or mode in self.registryValue('modesToAskWhenOpped',channel=channel):
            chan = self.getChan(irc,channel)
            for item in items:
                if item in chan.nicks or item in irc.state.channels[channel].users:
                    n = self.getNick(irc,item)
                    found = False
                    if self.registryValue('avoidOverlap',channel=channel):
                        modes = chan.getItemsFor(self.getIrcdMode(irc,mode,n.prefix)[0])
                        if len(modes):
                            for m in modes:
                                md = modes[m]
                                if match(md.value,n,irc,self.registryValue('resolveIp')):
                                    targets.append(md.value)
                                    found = True
                    if not found:
                        patterns = getBestPattern(n,irc,self.registryValue('useIpForGateway',channel=channel),self.registryValue('resolveIp'))
                        if len(patterns):
                            targets.append(patterns[0])
                elif ircutils.isUserHostmask(item) or self.getIrcdExtbansPrefix(irc) in item:
                    found = False
                    if self.registryValue('avoidOverlap',channel=channel):
                        modes = chan.getItemsFor(self.getIrcdMode(irc,mode,item)[0])
                        if len(modes):
                            for m in modes:
                                md = modes[m]
                                if ircutils.isUserHostmask(item):
                                    n = Nick(0)
                                    n.setPrefix(item)
                                    if match(md.value,n,irc,self.registryValue('resolveIp')):
                                        targets.append(md.value)
                                        found = True
                    if not found:
                        targets.append(item)
        n = 0
        for item in targets:
            r = self.getIrcdMode(irc,mode,item)
            if i.add(irc,channel,r[0],r[1],duration,msg.prefix,self.getDb(irc.network)):
                if perm:
                    chan = ircdb.channels.getChannel(channel)
                    chan.addBan(r[1],0)
                    ircdb.channels.setChannel(channel, chan)
                if reason:
                    f = None
                    if self.registryValue('announceInTimeEditAndMark',channel=channel):
                        if msg.prefix != irc.prefix and self.registryValue('announceMark',channel=channel):
                            f = self._logChan
                        elif msg.prefix == irc.prefix and self.registryValue('announceBotMark',channel=channel):
                            f = self._logChan
                    i.submark(irc,channel,mode,item,reason,msg.prefix,self.getDb(irc.network),self._logChan,self)
                n = n+1
        self.forceTickle = True
        self._tickle(irc)
        return len(items) <= n

    def _removes (self,irc,msg,args,channel,mode,items,perm=False):
        i = self.getIrc(irc)
        chan = self.getChan(irc,channel)
        targets = []
        massremove = False
        count = 0
        if mode in self.registryValue('modesToAsk',channel=channel) or mode in self.registryValue('modesToAskWhenOpped',channel=channel):
            for item in items:
                if item in i.nicks or item in irc.state.channels[channel].users:
                    n = self.getNick(irc,item)
                    L = chan.getItemsFor(self.getIrcdMode(irc,mode,n.prefix)[0])
                    # here we check active items against Nick and add each pattern which matchs him
                    for pattern in L:
                        m = match(L[pattern].value,n,irc,self.registryValue('resolveIp'))
                        if m:
                            targets.append(L[pattern].value)
                elif ircutils.isUserHostmask(item) or self.getIrcdExtbansPrefix(irc) in item:
                    targets.append(item)
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
                if perm:
                    chan = ircdb.channels.getChannel(channel)
                    try:
                        chan.removeBan(item)
                    except:
                        self.log.info('%s is not in Channel.ban' % item)
                    ircdb.channels.setChannel(channel, chan)
                if i.edit(irc,channel,r[0],r[1],0,msg.prefix,self.getDb(irc.network),None,f,self):
                    count = count + 1
        self.forceTickle = True
        self._tickle(irc)
        return len(items) <= count or massremove

    def getIrc (self,irc):
        # init irc db
        if not irc.network in self._ircs:
            i = self._ircs[irc.network] = Ircd (irc,self.registryValue('logsSize'))
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
                if not self.starting:
                    i.lowQueue.enqueue(ircmsgs.ping(channel))
                    i.lowQueue.enqueue(ircmsgs.who(channel, args=('%tuhnairf,1',)))
                self.forceTickle = True
        return i.getChan (irc,channel)

    def getNick (self,irc,nick):
        return self.getIrc(irc).getNick(irc,nick)

    def makeDb(self, filename):
        """ Create a database and connect to it. """
        if os.path.exists(filename):
            db = sqlite3.connect(filename,timeout=10)
            db.text_factory = str
            if self.dbUpgraded:
                return db
            c = db.cursor()
            try:
                c.execute("""SELECT id, pattern FROM patterns WHERE count=? LIMIT 1""",(0,))
                c.close()
            except:
                try:
                    c.execute("""CREATE TABLE patterns (
                    id INTEGER PRIMARY KEY,
                    channel VARCHAR(1000) NOT NULL,
                    oper VARCHAR(1000) NOT NULL,
                    at TIMESTAMP NOT NULL,
                    pattern VARCHAR(512) NOT NULL,
                    regexp INTEGER,
                    trigger INTEGER,
                    life INTEGER,
                    mode VARCHAR(1) NOT NULL,
                    duration INTEGER,
                    count INTEGER
                    )""")
                    db.commit()
                    c.close()
                except:
                    c.close()
            self.dbUpgraded = True
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
        c.execute("""CREATE TABLE patterns (
                id INTEGER PRIMARY KEY,
                channel VARCHAR(1000) NOT NULL,
                oper VARCHAR(1000) NOT NULL,
                at TIMESTAMP NOT NULL,
                pattern VARCHAR(512) NOT NULL,
                regexp INTEGER,
                trigger INTEGER,
                life INTEGER,
                mode VARCHAR(1) NOT NULL,
                duration INTEGER,
                count INTEGER
                )""")
        db.commit()
        c.close()
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
        if not self.lastTickle:
            self.lastTickle = t
        if not self.forceTickle:
            pool = self.registryValue('pool')
            if pool > 0:
                if self.lastTickle+pool < t:
                    return
        self.lastTickle = t
        i = self.getIrc(irc)
        retickle = False
        # send waiting msgs, here we mostly got kick messages
        while len(i.queue):
            irc.queueMsg(i.queue.dequeue())
        def f(L):
            return applymodes(channel,L)
        for channel in list(irc.state.channels.keys()):
            chan = self.getChan(irc,channel)
            # check expired items
            for mode in list(chan.getItems().keys()):
                for value in list(chan._lists[mode].keys()):
                    item = chan._lists[mode][value]
                    if item.expire != None and item.expire != item.when and not item.asked and item.expire <= t:
                        if mode == 'q' and self.registryValue('useChanServForQuiets',channel=channel) and not irc.nick in irc.state.channels[channel].ops and len(chan.queue) == 0:
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
                    if mode == '+q' and self.registryValue('useChanServForQuiets',channel=channel) and not irc.nick in irc.state.channels[channel].ops and len(chan.queue) == 1:
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
                    def f ():
                        chan.opAsked = False
                    schedule.addEvent(f,time.time() + 300)
                    irc.queueMsg(ircmsgs.IrcMsg(self.registryValue('opCommand',channel=channel).replace('$channel',channel).replace('$nick',irc.nick)))
                    retickle = True
            if len(chan.queue) or len(chan.action):
                if not irc.nick in irc.state.channels[channel].ops and not chan.opAsked:
                    # pending actions, but not opped
                    if not chan.deopAsked:
                        if not self.registryValue('doNothingAboutOwnOpStatus',channel=channel):
                            chan.opAsked = True
                            def f ():
                                chan.opAsked = False
                            schedule.addEvent(f,time.time() + 300)
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
                                mm = L[index][0].replace("+","")
                                if '+' in L[index][0] and mm in self.registryValue('modesToAsk',channel=channel):
                                    if mm in self.registryValue('kickMode',channel=channel) or self.registryValue('doActionAgainstAffected',channel=channel):
                                        adding = True
                                if mm in self.registryValue('modesToAskWhenOpped',channel=channel):
                                    adding = True
                                index = index + 1
                            # remove duplicates ( should not happens but .. )
                            S = set(L)
                            r = []
                            for item in L:
                                r.append(item)
                            # if glich, just comment this if...
                            if not len(chan.action) and not adding and not chan.attacked:
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
                        b = i.edit(irc,item.channel,item.mode,item.value,expire,prefix,self.getDb(irc.network),self._schedule,f,self)
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
                        i.mark(irc,item.uid,reason,prefix,self.getDb(irc.network),f,self)
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
                item = chan.addItem(mode,value,prefix,float(date),self.getDb(irc.network),False,self)
                # added expire date if new modes were added when the bot was offline
                expire = self.registryValue('autoExpire',channel=item.channel)
                if expire > 0 and item.isNew:
                    f = None
                    if self.registryValue('announceBotEdit',channel=item.channel):
                        f = self._logChan
                    i = self.getIrc(irc)
                    i.edit(irc,item.channel,item.mode,item.value,expire,irc.prefix,self.getDb(irc.network),self._schedule,f,self)
                    item.isNew = False
                    self.forceTickle = True
                item.isNew = False

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
                    if self.registryValue('useColorForAnnounces',channel=channel):
                        f(irc,channel,'[%s] sync %s' % (ircutils.bold(channel),chan.dones))
                    else:
                        f(irc,channel,'[%s] sync %s' % (channel,chan.dones))
            i.resync(irc,channel,mode,self.getDb(irc.network),f,self)
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
        if len(msg.args) == 9 and msg.args[1] == '1':
            (garbage,digit,ident,ip,host,nick,status,account,realname) = msg.args
            if account == '0':
                account = None
            n = self.getNick(irc,nick)
            prefix = '%s!%s@%s' % (nick,ident,host)
            n.setPrefix(prefix)
            if n.ip == None and ip != '255.255.255.255':
                # validate ip
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
                chan.syn = True
                if self.registryValue('announceModeSync',channel=channel):
                    if self.registryValue('useColorForAnnounces',channel=channel):
                        self._logChan(irc,channel,"[%s] is ready" % ircutils.bold(channel))
                    else:
                        self._logChan(irc,channel,"[%s] is ready" % channel)
        self._tickle(irc)

    def _logChan (self,irc,channel,message):
        # send messages to logChannel if configured for
        if channel in irc.state.channels:
            logChannel = self.registryValue('logChannel',channel=channel)
            if logChannel in irc.state.channels:
                i = self.getIrc(irc)
                if logChannel == channel and irc.nick in irc.state.channels[channel].ops and self.registryValue('keepOp',channel=channel):
                    if self.registryValue ('announceWithNotice',channel=channel):
                        i.lowQueue.enqueue(ircmsgs.IrcMsg('NOTICE @%s :%s' % (logChannel,message)))
                    else:
                        i.lowQueue.enqueue(ircmsgs.IrcMsg('PRIVMSG @%s :%s' % (logChannel,message)))
                else:
                    if self.registryValue ('announceWithNotice',channel=channel):
                        i.lowQueue.enqueue(ircmsgs.notice(logChannel,message))
                    else:
                        i.lowQueue.enqueue(ircmsgs.privmsg(logChannel,message))
                self.forceTickle = True

    def resolve (self,irc,channels,prefix):
        i = self.getIrc(irc)
        (nick,ident,host) = ircutils.splitHostmask(prefix)
        n = self.getNick(irc,nick)
        if n:
            (nick,ident,host) = ircutils.splitHostmask(n.prefix)
            if not n.prefix in cache and not '/' in host:
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
                            n.setIp(L[0])
                except:
                    t = ''
                if n.ip != None:
                    cache[n.prefix] = n.ip
                else:
                    cache[n.prefix] = host
        for channel in channels:
            if ircutils.isChannel(channel) and channel in irc.state.channels:
                best = getBestPattern(n,irc,self.registryValue('useIpForGateway',channel=channel),self.registryValue('resolveIp'))[0]
                chan = self.getChan(irc,channel)
                banned = False
                if self.registryValue('checkEvade',channel=channel) and '/ip.' in prefix:
                    items = chan.getItemsFor('b')
                    for k in items:
                        item = items[k]
                        if ircutils.isUserHostmask(item.value):
                            n = Nick(0)
                            n.setPrefix(item.value)
                            if match('*!*@%s' % prefix.split('ip.')[1],n,irc,self.registryValue('resolveIp')):
                                self._act (irc,channel,'b',best,self.registryValue('autoExpire',channel=channel),'evade of [#%s +%s %s]' % (item.uid,item.mode,item.value))
                                f = None
                                banned = True
                                self.forceTickle = True
                                if self.registryValue('announceBotMark',channel=channel):
                                    f = self._logChan
                                i.mark(irc,item.uid,'evade with %s --> %s' % (prefix,best),irc.prefix,self.getDb(irc.network),f,self)
                                break
                    if not banned:
                        items = chan.getItemsFor('q')
                        for k in items:
                            item = items[k]
                            if ircutils.isUserHostmask(item.value):
                                n = Nick(0)
                                n.setPrefix(item.value)
                                pat = '*!*@%s' % prefix.split('ip.')[1]
                                if pat != item.value and match(pat,n,irc,self.registryValue('resolveIp')):
                                    f = None
                                    if self.registryValue('announceBotMark',channel=channel):
                                        f = self._logChan
                                    i.mark(irc,item.uid,'evade with %s --> %s' % (prefix,best),irc.prefix,self.getDb(irc.network),f,self)
                                    break
        self._tickle(irc)

    def doJoin (self,irc,msg):
        channels = msg.args[0].split(',')
        n = self.getNick(irc,msg.nick)
        n.setPrefix(msg.prefix)
        i = self.getIrc(irc)
        if len(msg.args) == 3:
            n.setRealname(msg.args[2])
            n.setAccount(msg.args[1])
        if msg.nick == irc.nick:
            self.forceTickle = True
            self._tickle(irc)
            return
        if self.registryValue('resolveIp') and not '/' in msg.prefix.split('@')[1] and n.ip == None:
            t = world.SupyThread(target=self.resolve,name=format('Resolving %s for %s', msg.prefix, channels),args=(irc,channels,msg.prefix))
            t.setDaemon(True)
            t.start()
        for channel in channels:
            if ircutils.isChannel(channel) and channel in irc.state.channels:
                best = getBestPattern(n,irc,self.registryValue('useIpForGateway',channel=channel),self.registryValue('resolveIp'))[0]
                chan = self.getChan(irc,channel)
                chan.nicks[msg.nick] = True
                n.addLog(channel,'has joined')
                banned = False
                c = ircdb.channels.getChannel(channel)
                if not self._isVip(irc,channel,n) and not chan.netsplit:
                    if c.bans and len(c.bans) and self.registryValue('useChannelBansForPermanentBan',channel=channel):
                        for ban in list(c.bans):
                            if match (ban,n,irc,self.registryValue('resolveIp')):
                                if i.add(irc,channel,'b',best,self.registryValue('autoExpire',channel=channel),irc.prefix,self.getDb(irc.network)):
                                    banned = True
                                    self.forceTickle = True
                                    break
                    if not banned:
                        isMassJoin = self._isSomething(irc,channel,channel,'massJoin')
                        if isMassJoin:
                            if self.registryValue('massJoinMode',channel=channel) == 'd':
                                if self.registryValue('useColorForAnnounces',channel=channel):
                                    self._logChan(irc,channel,'[%s] massJoinMode applied' % ircutils.bold(channel))
                                else:
                                    self._logChan(irc,channel,'[%s] massJoinMode applied' % channel)
                            else:
                                chan.action.enqueue(ircmsgs.IrcMsg('MODE %s %s' % (channel,self.registryValue('massJoinMode',channel=channel))))
                            def unAttack():
                                if channel in list(irc.state.channels.keys()):
                                    if self.registryValue('massJoinUnMode',channel=channel) == 'd':
                                        if self.registryValue('useColorForAnnounces',channel=channel):
                                            self._logChan(irc,channel,'[%s] massJoinUnMode applied' % ircutils.bold(channel))
                                        else:
                                            self._logChan(irc,channel,'[%s] massJoinUnMode applied' % channel)
                                    else:
                                        chan.action.enqueue(ircmsgs.IrcMsg('MODE %s %s' % (channel,self.registryValue('massJoinUnMode',channel=channel))))
                            schedule.addEvent(unAttack,float(time.time()+self.registryValue('massJoinDuration',channel=channel)))
                            self.forceTickle = True
                    if not banned:
                        permit = self.registryValue('clonePermit',channel=channel)
                        if permit > -1:
                            clones = []
                            for nick in list(irc.state.channels[channel].users):
                                n = self.getNick(irc,nick)
                                m = match(best,n,irc,self.registryValue('resolveIp'))
                                if m:
                                    clones.append(nick)
                            if len(clones) > permit:
                                if self.registryValue('cloneMode',channel=channel) == 'd':
                                    self._logChan(irc,channel,'[%s] clones (%s) detected (%s)' % (ircutils.bold(channel),best,', '.join(clones)))
                                else:
                                    r = self.getIrcdMode(irc,self.registryValue('cloneMode',channel=channel),best)
                                    self._act(irc,channel,r[0],r[1],self.registryValue('cloneDuration',channel=channel),self.registryValue('cloneComment',channel))
                                    self.forceTickle = True
        self._tickle(irc)

    def doPart (self,irc,msg):
        isBot = msg.prefix == irc.prefix
        channels = msg.args[0].split(',')
        i = self.getIrc(irc)
        n = self.getNick(irc,msg.nick)
        n.setPrefix(msg.prefix)
        reason = ''
        if len(msg.args) == 2:
            reason = msg.args[1].lstrip().rstrip()
        canRemove = True
        for channel in channels:
            if isBot and channel in i.channels:
                del i.channels[channel]
                continue
            if ircutils.isChannel(channel) and channel in irc.state.channels:
                best = getBestPattern(n,irc,self.registryValue('useIpForGateway',channel=channel),self.registryValue('resolveIp'))[0]
                if len(reason):
                    if reason.startswith('requested by') and self.registryValue('announceKick',channel=channel):
                        if self.registryValue('useColorForAnnounces',channel=channel):
                            self._logChan(irc,channel,'[%s] %s has left (%s)' % (ircutils.bold(channel),ircutils.mircColor(msg.prefix,'light blue'),reason))
                        else:
                            self._logChan(irc,channel,'[%s] %s has left (%s)' % (channel,msg.prefix,reason))
                        if self.registryValue('addKickMessageInComment',channel=channel):
                            chan = self.getChan(irc,channel)
                            found = None
                            for mode in self.registryValue('modesToAsk',channel=channel):
                                items = chan.getItemsFor(mode)
                                for k in items:
                                    item = items[k]
                                    f = match(item.value,n,irc,self.registryValue('resolveIp'))
                                    if f:
                                        found = item
                                        break
                                if found:
                                    break
                            if found:
                                f = None
                                if self.registryValue('announceBotMark',channel=channel):
                                    f = self._logChan
                                i.mark(irc,found.uid,reason,irc.prefix,self.getDb(irc.network),f,self)
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
                            forward = self.registryValue('cycleForward',channel=channel)
                            if kind == 'cycle' and len(forward):
                                best = best + '$' + forward
                            r = self.getIrcdMode(irc,mode,best)
                            self._act(irc,channel,r[0],r[1],duration,comment)
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
            if self.registryValue('useColorForAnnounces',channel=channel):
                self._logChan(irc,channel,'[%s] %s kicks %s (%s)' % (ircutils.bold(channel),msg.nick,ircutils.mircColor(n.prefix,'light blue'),reason))
            else:
                self._logChan(irc,channel,'[%s] %s kicks %s (%s)' % (channel,msg.nick,n.prefix,reason))
        if len(reason) and msg.prefix != irc.prefix and self.registryValue('addKickMessageInComment',channel=channel):
            chan = self.getChan(irc,channel)
            found = None
            for mode in self.registryValue('modesToAsk',channel=channel):
                items = chan.getItemsFor(mode)
                for k in items:
                    item = items[k]
                    f = match(item.value,n,irc,self.registryValue('resolveIp'))
                    if f:
                        found = item
                        break
                if found:
                    break
            if found:
                f = None
                if self.registryValue('announceBotMark',channel=channel):
                    f = self._logChan
                i = self.getIrc(irc)
                i.mark(irc,found.uid,'kicked by %s (%s)' % (msg.nick,reason),irc.prefix,self.getDb(irc.network),f,self)
        self._tickle(irc)

    def _rmNick (self,irc,n):
        def nrm():
            patterns = getBestPattern(n,irc,self.registryValue('useIpForGateway'),self.registryValue('resolveIp'))
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
                for channel in irc.state.channels:
                    best = getBestPattern(n,irc,self.registryValue('useIpForGateway',channel=channel),self.registryValue('resolveIp'))[0]
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

    def _split (self,irc,channel):
        chan = self.getChan(irc,channel)
        if not chan.netsplit:
            def f(L):
                return applymodes(channel,L)
            chan.netsplit = True
            def d ():
                chan.netsplit = False
                unmodes = self.registryValue('netsplitUnmodes',channel=channel)
                if len(unmodes):
                    if unmodes == 'd':
                        if self.registryValue('useColorForAnnounces',channel=channel):
                            self._logChan(irc,channel,'[%s] netsplitUnmodes applied' % ircutils.bold(channel))
                        else:
                            self._logChan(irc,channel,'[%s] netsplitUnmodes applied' % channel)
                    else:
                        chan.action.enqueue(ircmsgs.IrcMsg('MODE %s %s' % (channel,unmodes)))
                    self.forceTickle = True
                    self._tickle(irc)
            schedule.addEvent(d,time.time()+self.registryValue('netsplitDuration',channel=channel)+1)
            modes = self.registryValue('netsplitModes',channel=channel)
            if len(modes):
                if modes == 'd':
                    if self.registryValue('useColorForAnnounces',channel=channel):
                        self._logChan(irc,channel,'[%s] netsplitModes applied' % ircutils.bold(channel))
                    else:
                        self._logChan(irc,channel,'[%s] netsplitModes applied' % channel)
                else:
                    chan.action.enqueue(ircmsgs.IrcMsg('MODE %s %s' % (channel,modes)))
                self.forceTickle = True
                self._tickle(irc)

    def doQuit (self,irc,msg):
        isBot = msg.nick == irc.nick
        reason = None
        if len(msg.args) == 1:
            reason = msg.args[0].lstrip().rstrip()
        if reason and reason == '*.net *.split':
            for channel in irc.state.channels:
                chan = self.getChan(irc,channel)
                if msg.nick in chan.nicks and not chan.netsplit:
                    self._split(irc,channel)
        removeNick = True
        if isBot:
            self._ircs = ircutils.IrcDict()
            return
        if not isBot:
            n = self.getNick(irc,msg.nick)
            patterns = getBestPattern(n,irc,self.registryValue('useIpForGateway'),self.registryValue('resolveIp'))
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
                if not 'Nickname regained by services' in reason:
                    for channel in irc.state.channels:
                        chan = self.getChan(irc,channel)
                        if msg.nick in chan.nicks:
                            if self.registryValue('announceKick',channel=channel):
                                if self.registryValue('useColorForAnnounces',channel=channel):
                                    self._logChan(irc,channel,'[%s] %s has quit (%s)' % (ircutils.bold(channel),ircutils.mircColor(msg.prefix,'light blue'),ircutils.mircColor(reason,'red')))
                                else:
                                    self._logChan(irc,channel,'[%s] %s has quit (%s)' % (channel,msg.prefix,reason))
            for channel in irc.state.channels:
                chan = self.getChan(irc,channel)
                if msg.nick in chan.nicks:
                    if not self._isVip(irc,channel,n):
                        best = getBestPattern(n,irc,self.registryValue('useIpForGateway',channel=channel),self.registryValue('resolveIp'))[0]
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
                            forward = self.registryValue('cycleForward',channel=channel)
                            if kind == 'cycle' and len(forward):
                                best = best + '$' + forward
                            r = self.getIrcdMode(irc,mode,best)
                            self._act(irc,channel,r[0],r[1],duration,comment)
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
            patterns = getBestPattern(n,irc,self.registryValue('useIpForGateway'),self.registryValue('resolveIp'))
            if len(patterns):
                best = patterns[0]
            if not best:
                return
            for channel in irc.state.channels:
                best = getBestPattern(n,irc,self.registryValue('useIpForGateway',channel=channel),self.registryValue('resolveIp'))[0]
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
                        r = self.getIrcdMode(irc,mode,best)
                        self._act(irc,channel,r[0],r[1],duration,comment)
                        self.forceTickle = True
        self._tickle(irc)

    def doCap (self,irc,msg):
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
                                        f = match(items[item].value,n,irc,self.registryValue('resolveIp'))
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
                            r = self.getIrcdMode(irc,found.mode,getBestPattern(n,irc,self.registryValue('useIpForGateway',channel=channel),self.registryValue('resolveIp'))[0])
                            self._act (irc,channel,r[0],r[1],duration,'evade of [#%s +%s %s]' % (found.uid,found.mode,found.value))
                            f = None
                            if self.registryValue('announceBotMark',channel=found.channel):
                                f = self._logChan
                            i.mark(irc,found.uid,'evade with %s --> %s' % (msg.prefix,getBestPattern(n,irc,self.registryValue('useIpForGateway',channel=channel),self.registryValue('resolveIp'))[0]),irc.prefix,self.getDb(irc.network),f,self)
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
            patterns = getBestPattern(n,irc,self.registryValue('useIpForGateway'),self.registryValue('resolveIp'))
            best = False
            if len(patterns):
                best = patterns[0]
            if not best:
                return
            for channel in targets.split(','):
                if irc.isChannel(channel) and channel in irc.state.channels:
                    best = getBestPattern(n,irc,self.registryValue('useIpForGateway',channel=channel),self.registryValue('resolveIp'))[0]
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
                            r = self.getIrcdMode(irc,mode,best)
                            self._act(irc,channel,r[0],r[1],duration,comment)
                            self._isBad(irc,channel,best)
                            self.forceTickle = True
                        if isNotice:
                            isBad = self._isSomething(irc,channel,best,'bad')
                        if not isMass:
                            if isNotice or isBad:
                                kind = None
                                if isBad:
                                    kind = 'bad'
                                else:
                                    kind = 'notice'
                                mode = self.registryValue('%sMode' % kind,channel=channel)
                                duration = self.registryValue('%sDuration' % kind,channel=channel)
                                comment = self.registryValue('%sComment' % kind,channel=channel)
                                r = self.getIrcdMode(irc,mode,best)
                                self._act(irc,channel,r[0],r[1],duration,comment)
                                self.forceTickle = True
                    if self.registryValue('announceNotice',channel=channel):
                        if not chan.isWrong(best):
                            if self.registryValue('useColorForAnnounces',channel=channel):
                                self._logChan(irc,channel,'[%s] %s notice "%s"' % (ircutils.bold(channel),ircutils.mircColor(msg.prefix,'light blue'),text))
                            else:
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
        if n.prefix == irc.prefix:
            return True
        protected = ircdb.makeChannelCapability(channel, 'protected')
        if ircdb.checkCapability(n.prefix, protected):
            return True
        return False

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
            patterns = getBestPattern(n,irc,self.registryValue('useIpForGateway'),self.registryValue('resolveIp'))
            if len(patterns):
                best = patterns[0]
            # if it fails here stacktrace
        if not n or not best:
            # server msgs or plugin reload, or state not ready
            self._tickle(irc)
            return
        for channel in recipients.split(','):
            if irc.isChannel(channel) and channel in irc.state.channels:
                best = getBestPattern(n,irc,self.registryValue('useIpForGateway',channel=channel),self.registryValue('resolveIp'))[0]
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
                    isPattern = False
                    for p in chan.patterns:
                        pattern = chan.patterns[p]
                        if pattern.match(text):
                            if pattern.limit == 0:
                                isPattern = pattern
                                break
                            else:
                                prop = 'Pattern%s' % pattern.uid
                                key = best
                                if not prop in chan.spam:
                                    chan.spam[prop] = {}
                                if not key in chan.spam[prop] or chan.spam[prop][key].timeout != pattern.life:
                                    chan.spam[prop][key] = utils.structures.TimeoutQueue(pattern.life)
                                chan.spam[prop][key].enqueue(key)
                                if len(chan.spam[prop][key]) > pattern.limit:
                                    chan.spam[prop][key].reset()
                                    isPattern = pattern
                                    break
                    if isPattern:
                         r = self.getIrcdMode(irc,isPattern.mode,best)
                         self._act(irc,channel,r[0],r[1],isPattern.duration,'matches #%s' % isPattern.uid)
                         isBad = self._isBad(irc,channel,best)
                         self.forceTickle = True
                         chan.countpattern(isPattern.uid,self.getDb(irc.network))
                    elif not isPattern and isMass:
                        kind = 'massRepeat'
                        mode = self.registryValue('%sMode' % kind,channel=channel)
                        duration = self.registryValue('%sDuration' % kind,channel=channel)
                        comment = self.registryValue('%sComment' % kind,channel=channel)
                        r = self.getIrcdMode(irc,mode,best)
                        self._act(irc,channel,r[0],r[1],duration,comment)
                        self._isBad(irc,channel,best)
                        self.forceTickle = True
                    elif not isPattern and not isMass:
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
                            r = self.getIrcdMode(irc,mode,best)
                            self._act(irc,channel,r[0],r[1],duration,comment)
                            self.forceTickle = True
                if not chan.isWrong(best):
                    # prevent the bot to flood logChannel with bad user craps
                    if self.registryValue('announceCtcp',channel=channel) and isCtcpMsg and not isAction:
                        if self.registryValue('useColorForAnnounces',channel=channel):
                            self._logChan(irc,channel,'[%s] %s ctcps "%s"' % (ircutils.bold(channel),ircutils.mircColor(msg.prefix,'light blue'),text))
                        else:
                            self._logChan(irc,channel,'[%s] %s ctcps "%s"' % (channel,msg.prefix,text))
                        self.forceTickle = True
                    else:
                        if self.registryValue('announceOthers',channel=channel) and irc.nick in irc.state.channels[channel].ops and 'z' in irc.state.channels[channel].modes:
                            message = None
                            if 'm' in irc.state.channels[channel].modes:
                                if not msg.nick in irc.state.channels[channel].voices and not msg.nick in irc.state.channels[channel].ops:
                                    if self.registryValue('useColorForAnnounces',channel=channel):
                                        message = '[%s] [+m] <%s> %s' % (ircutils.bold(channel),ircutils.mircColor(msg.prefix,'light blue'),text)
                                    else:
                                        message = '[%s] [+m] <%s> %s' % (channel,msg.prefix,text)
                            if not message:
                                if not msg.nick in irc.state.channels[channel].voices and not msg.nick in irc.state.channels[channel].ops:
                                    modes = self.registryValue('modesToAsk',channel=channel)
                                    found = False
                                    for mode in modes:
                                        items = chan.getItemsFor(mode)
                                        for item in items:
                                            f = match(items[item].value,n,irc,self.registryValue('resolveIp'))
                                            if f:
                                                found = [items[item],f]
                                            if found:
                                                break
                                        if found:
                                            break
                                    if found:
                                        if self.registryValue('useColorForAnnounces',channel=channel):
                                            message = '[%s] [#%s +%s %s] <%s> %s' % (ircutils.bold(channel),found[0].uid,ircutils.mircColor(found[0].mode,'red'),ircutils.mircColor(found[0].value,'light blue'),msg.nick,text)
                                        else:
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
                    i.askedItems[msg.prefix][found[0]][6] = True
                    i.lowQueue.enqueue(ircmsgs.privmsg(msg.nick,found[5]))
                    self.forceTickle = True
        self._tickle(irc)

    def hasAskedItems(self,irc,prefix,remove):
        i = self.getIrc(irc)
        if prefix in i.askedItems:
            found = None
            for item in i.askedItems[prefix]:
                if not found or item < found[0] and not found[6]:
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
            i.askedItems[prefix][data[0]][6] = True
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
                i.askedItems[prefix][found[0]][6] = True
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
                if self.registryValue('useColorForAnnounces',channel=channel):
                    self._logChan(irc,channel,'[%s] %s sets topic "%s"' % (ircutils.bold(channel),ircutils.mircColor(msg.prefix,'light blue'),msg.args[1]))
                else:
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

    def hasExtendedSharedBan (self,irc,fromChannel,target,mode):
        # todo add support for others ircd if supported, currently only freenode
        b = '%sj:%s' % (self.getIrcdExtbansPrefix(irc),fromChannel)
        kicks = []
        for channel in irc.state.channels:
            if b in irc.state.channels[channel].bans and mode in self.registryValue('kickMode',channel=channel) and not target.startswith('m:'):
                L = []
                for nick in list(irc.state.channels[channel].users):
                    L.append(nick)
                for nick in L:
                    if not self._isVip(irc,channel,self.getNick(irc,nick)):
                        n = self.getNick(irc,nick)
                        m = match(target,n,irc,self.registryValue('resolveIp'))
                        if m:
                            if len(kicks) < self.registryValue('kickMax',channel=channel):
                                if nick != irc.nick:
                                    kicks.append([nick,channel])
        if len(kicks):
            for kick in kicks:
                chan = self.getChan(irc,kick[1])
                chan.action.enqueue(ircmsgs.kick(kick[1],kick[0],random.choice(self.registryValue('kickMessage',channel=kick[1]))))
            self.forceTickle = True

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
        tolift = []
        if irc.isChannel(channel) and msg.args[1:] and channel in irc.state.channels:
            modes = ircutils.separateModes(msg.args[1:])
            chan = self.getChan(irc,channel)
            msgs = []
            announces = list(self.registryValue('announceModes',channel=channel))
            overexpire = self.registryValue('autoExpire',channel=channel)
            for change in modes:
                (mode,value) = change
                m = mode[1:]
                if value:
                    value = str(value).lstrip().rstrip()
                    item = None
                    if '+' in mode:
                        if m in self.registryValue('modesToAskWhenOpped',channel=channel) or m in self.registryValue('modesToAsk',channel=channel):
                            item = chan.addItem(m,value,msg.prefix,now,self.getDb(irc.network),self.registryValue('trackAffected',channel=channel),self)
                            if msg.nick != irc.nick and self.registryValue('askOpAboutMode',channel=channel) and ircdb.checkCapability(msg.prefix, '%s,op' % channel):
                                data = [item.uid,m,value,channel,msg.prefix,'For [#%s %s %s in %s - %s user(s)] type <duration> <reason>, you have 3 minutes' % (item.uid,'+%s' % m,value,channel,len(item.affects)),False]
                                if self.registryValue('useColorForAnnounces',channel=channel):
                                    data[5] = 'For [#%s %s %s in %s - %s user(s)] type <duration> <reason>, you have 3 minutes' % (ircutils.mircColor(item.uid,'yellow','black'),ircutils.bold(ircutils.mircColor('+%s' % m,'green')),ircutils.mircColor(value,'light blue'),channel,len(item.affects))
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
                                if m in self.registryValue('modesToAsk',channel=channel) and self.registryValue('doActionAgainstAffected',channel=channel) and not irc.nick == nick:
                                    for k in list(chan.getItems()):
                                        if k in self.registryValue('modesToAskWhenOpped',channel=channel):
                                            items = chan.getItemsFor(k)
                                            if len(items):
                                                for active in items:
                                                    active = items[active]
                                                    if match(active.value,self.getNick(irc,nick),irc,self.registryValue('resolveIp')):
                                                        tolift.append(active)
                                kicked = False
                                if m in self.registryValue('kickMode',channel=channel) and not value.startswith('m:'): #  and not value.startswith(self.getIrcdExtbans(irc)) works for unreal
                                    if msg.nick == irc.nick or msg.nick == 'ChanServ' or self.registryValue('kickOnMode',channel=channel):
                                        if self.registryValue('kickMax',channel=channel) < 0 or len(item.affects) < self.registryValue('kickMax',channel=channel):
                                            if nick in irc.state.channels[channel].users and nick != irc.nick:
                                                chan.action.enqueue(ircmsgs.kick(channel,nick,random.choice(self.registryValue('kickMessage',channel=channel))))
                                                self.forceTickle = True
                                                kicked = True
                                if not kicked and m in self.registryValue('modesToAsk',channel=channel) and self.registryValue('doActionAgainstAffected',channel=channel):
                                    if msg.nick == irc.nick or msg.nick == 'ChanServ':
                                        if nick in irc.state.channels[channel].ops and not nick == irc.nick:
                                            chan.queue.enqueue(('-o',nick))
                                        if nick in irc.state.channels[channel].halfops and not nick == irc.nick:
                                            chan.queue.enqueue(('-h',nick))
                                        if nick in irc.state.channels[channel].voices and not nick == irc.nick:
                                            chan.queue.enqueue(('-v',nick))
                                        if m == 'q' and len(self.registryValue('quietMessage',channel=channel)) and not chan.attacked:
                                            qm = self.registryValue('quietMessage',channel=channel)
                                            if self.registryValue('quietNotice',channel=channel):
                                                irc.queueMsg(ircmsgs.notice(nick,qm))
                                            else:
                                                irc.queueMsg(ircmsgs.privmsg(nick,qm))
                        if m in self.registryValue('kickMode',channel=channel) and not value.startswith('m:'):
                            self.hasExtendedSharedBan(irc,channel,value,m)
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
                                if m in announces:
                                    if self.registryValue('useColorForAnnounces',channel=channel):
                                        msgs.append('[#%s %s %s]' % (ircutils.mircColor(str(item.uid),'yellow','black'),ircutils.bold(ircutils.mircColor(mode,'red')),ircutils.mircColor(value,'light blue')))
                                    else:
                                        msgs.append('[#%s %s %s]' % (str(item.uid),mode,value))
                            elif len(item.affects) != 1:
                                if m in announces:
                                    if self.registryValue('useColorForAnnounces',channel=channel):
                                        msgs.append('[#%s %s %s - %s users]' % (ircutils.mircColor(str(item.uid),'yellow','black'),ircutils.bold(ircutils.mircColor(mode,'red')),ircutils.mircColor(value,'light blue'),str(len(item.affects))))
                                    else:
                                        msgs.append('[#%s %s %s - %s users]' % (str(item.uid),mode,value,str(len(item.affects))))
                            else:
                                if m in announces:
                                    if self.registryValue('useColorForAnnounces',channel=channel):
                                        msgs.append('[#%s %s %s - %s]' % (ircutils.mircColor(str(item.uid),'yellow','black'),ircutils.bold(ircutils.mircColor(mode,'red')),ircutils.mircColor(value,'light blue'),item.affects[0]))
                                    else:
                                        msgs.append('[#%s %s %s - %s]' % (str(item.uid),mode,value,item.affects[0]))
                        else:
                            if not len(item.affects):
                                if m in announces:
                                    if self.registryValue('useColorForAnnounces',channel=channel):
                                        msgs.append('[#%s %s %s %s]' % (ircutils.mircColor(str(item.uid),'yellow','black'),ircutils.bold(ircutils.mircColor(mode,'green')),ircutils.mircColor(value,'light blue'),str(utils.timeElapsed(item.removed_at-item.when))))
                                    else:
                                        msgs.append('[#%s %s %s %s]' % (str(item.uid),mode,value,str(utils.timeElapsed(item.removed_at-item.when))))
                            elif len(item.affects) != 1:
                                if m in announces:
                                    if self.registryValue('useColorForAnnounces',channel=channel):
                                        msgs.append('[#%s %s %s - %s users, %s]' % (ircutils.mircColor(str(item.uid),'yellow','black'),ircutils.bold(ircutils.mircColor(mode,'green')),ircutils.mircColor(value,'light blue'),str(len(item.affects)),str(utils.timeElapsed(item.removed_at-item.when))))
                                    else:
                                        msgs.append('[#%s %s %s - %s users, %s]' % (str(item.uid),mode,value,str(len(item.affects)),str(utils.timeElapsed(item.removed_at-item.when))))
                            else:
                                if m in announces:
                                    if self.registryValue('useColorForAnnounces',channel=channel):
                                        msgs.append('[#%s %s %s - %s, %s]' % (ircutils.mircColor(str(item.uid),'yellow','black'),ircutils.bold(ircutils.mircColor(mode,'green')),ircutils.mircColor(value,'light blue'),item.affects[0],str(utils.timeElapsed(item.removed_at-item.when))))
                                    else:
                                        msgs.append('[#%s %s %s - %s, %s]' % (str(item.uid),mode,value,item.affects[0],str(utils.timeElapsed(item.removed_at-item.when))))
                    else:
                        if m in announces:
                            if self.registryValue('useColorForAnnounces',channel=channel):
                                if '+' in mode:
                                    msgs.append('[%s %s]' % (ircutils.bold(ircutils.mircColor(mode,'red')),ircutils.mircColor(value,'light blue')))
                                else:
                                    msgs.append('[%s %s]' % (ircutils.bold(ircutils.mircColor(mode,'green')),ircutils.mircColor(value,'light blue')))
                            else:
                                msgs.append('[%s %s]' % (mode,value))
                else:
                    if n:
                        n.addLog(channel,'sets %s' % mode)
                    if m in announces:
                        if self.registryValue('useColorForAnnounces',channel=channel):
                            if '+' in mode:
                                msgs.append(ircutils.bold(ircutils.mircColor(mode,'red')))
                            else:
                                msgs.append(ircutils.bold(ircutils.mircColor(mode,'green')))
                        else:
                            msgs.append(mode)
            if toCommit:
                db.commit()

            if irc.nick in irc.state.channels[channel].ops and not self.registryValue('keepOp',channel=channel):
                self.forceTickle = True
            if len(self.registryValue('announceModes',channel=channel)) and len(msgs):
                if self.registryValue('announceModeMadeByIgnored',channel=channel) or not ircdb.checkIgnored(msg.prefix,channel):
                    if self.registryValue('useColorForAnnounces',channel=channel):
                        self._logChan(irc,channel,'[%s] %s sets %s' % (ircutils.bold(channel),msg.nick,' '.join(msgs)))
                    else:
                        self._logChan(irc,channel,'[%s] %s sets %s' % (channel,msg.nick,' '.join(msgs)))
                    self.forceTickle = True
            if len(toexpire):
                for item in toexpire:
                    f = None
                    if self.registryValue('announceBotEdit',channel=item.channel):
                        f = self._logChan
                    i.edit(irc,item.channel,item.mode,item.value,self.registryValue('autoExpire',channel=item.channel),irc.prefix,self.getDb(irc.network),self._schedule,f,self)
                self.forceTickle = True
            if len(tolift):
                for item in tolift:
                    f = None
                    if self.registryValue('announceBotEdit',channel=item.channel):
                        f = self._logChan
                    i.edit(irc,item.channel,item.mode,item.value,0,irc.prefix,self.getDb(irc.network),self._schedule,f,self)
                self.forceTickle = True
        c.close()
        # as _tickle now may be a bit too earlier, delay it a bit
        def ttickle():
            self._tickle(irc)
        schedule.addEvent(ttickle,time.time()+1)

    def do474(self,irc,msg):
        # bot banned from a channel it's trying to join
        # server 474 irc.nick #channel :Cannot join channel (+b) - you are banned
        # TODO talk with owner
        self._tickle(irc)

    def do478(self,irc,msg):
        # message when ban list is full after adding something to eqIb list
        (nick,channel,ban,info) = msg.args
        if self.registryValue('logChannel',channel=channel) in irc.state.channels:
            L = []
            for user in list(irc.state.channels[self.registryValue('logChannel',channel=channel)].users):
                L.append(user)
            if self.registryValue('useColorsForAnnounce',channel=channel):
                self._logChannel(irc,channel,'[%s] %s : %s' % (ircutils.bold(channel),ircutils.bold(ircutils.mircColor(info,'red')),' '.join(L)))
            else:
                self._logChan(irc,channel,'[%s] %s : %s' % (channel,info,' '.join(L)))
        self._tickle(irc)

     # protection features

    def _act (self,irc,channel,mode,mask,duration,reason):
        if mode == 'd':
            if self.registryValue('logChannel',channel=channel) in irc.state.channels:
                self._logChan(irc,channel,'[%s] debug %s %s %s %s' % (channel,mode,mask,duration,reason))
            return
        if mode in self.registryValue('modesToAsk',channel=channel) or mode in self.registryValue('modesToAskWhenOpped',channel=channel):
            i = self.getIrc(irc)
            if i.add(irc,channel,mode,mask,duration,irc.prefix,self.getDb(irc.network)):
                if reason and len(reason):
                    f = None
                    if self.registryValue('announceInTimeEditAndMark',channel=channel):
                        if self.registryValue('announceBotMark',channel=channel):
                            f = self._logChan
                    i.submark(irc,channel,mode,mask,reason,irc.prefix,self.getDb(irc.network),f,self)
            else:
                # increase duration, until the wrong action stopped
                f = None
                if self.registryValue('announceBotEdit',channel=channel):
                    f = self._logChan
                chan = self.getChan(irc,channel)
                item = chan.getItem(mode,mask)
                oldDuration = int(item.expire-item.when)
                i.edit(irc,channel,mode,mask,int(oldDuration+duration),irc.prefix,self.getDb(irc.network),self._schedule,f,self)
                if reason and len(reason):
                    f = None
                    if self.registryValue('announceBotMark',channel=channel):
                        f = self._logChan
                    i.mark(irc,item.uid,reason,irc.prefix,self.getDb(irc.network),f,self)
            self.forceTickle = True
            self._tickle(irc)
        else:
            results = []
            i = self.getIrc(irc)
            for nick in list(irc.state.channels[channel].users):
                if nick in i.nicks and nick != irc.nick:
                    n = self.getNick(irc,nick)
                    m = match(mask,n,irc,self.registryValue('resolveIp'))
                    if m:
                        results.append(nick)
            if len(results) and mode in 'kr':
                chan = self.getChan(irc,channel)
                if not reason or not len(reason):
                    reason = random.choice(self.registryValue('kickMessage',channel=channel))
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
        chan = self.getChan(irc,channel)
        if prop == 'massJoin' or prop == 'cycle':
            if chan.netsplit:
                return False
        limit = self.registryValue('%sPermit' % prop,channel=channel)
        if limit < 0:
            return False
        flag = ircdb.makeChannelCapability(channel, prop)
        if not ircdb.checkCapability(key, flag):
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
            chan = self.getChan(irc,channel)
            if self._isSomething(irc,channel,channel,'attack') and not chan.attacked:
                # if number of bad users raise the allowed limit, bot has to set channel attackmode
                # todo retreive all wrong users and find the best pattern to use against them
                chan.attacked = True
                if self.registryValue('attackMode',channel=channel) == 'd':
                    if self.registryValue('useColorForAnnounces',channel=channel):
                        self._logChan(irc,channel,'[%s] attackMode applied' % ircutils.bold(channel))
                    else:
                        self._logChan(irc,channel,'[%s] attackMode applied' % channel)
                else:
                    chan.action.enqueue(ircmsgs.IrcMsg('MODE %s %s' % (channel,self.registryValue('attackMode',channel=channel))))
                def unAttack():
                    if channel in list(irc.state.channels.keys()):
                        if self.registryValue('attackUnMode',channel=channel) == 'd':
                            if self.registryValue('useColorForAnnounces',channel=channel):
                                self._logChan(irc,channel,'[%s] attackUnMode applied' % ircutils.bold(channel))
                            else:
                                self._logChan(irc,channel,'[%s] attackUnMode applied' % channel)
                        else:
                            chan.action.enqueue(ircmsgs.IrcMsg('MODE %s %s' % (channel,self.registryValue('attackUnMode',channel=channel))))
                        chan.attacked = False
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
        users = []
        msg = message.lower()
        for user in list(irc.state.channels[channel].users):
            if len(user) > 2:
                users.append(user.lower())
        for user in users:
                if user in msg:
                    count = count + 1
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
        message = message.lower()
        chan = self.getChan(irc,channel)
        life = self.registryValue('massRepeatLife',channel=channel)
        if not channel in chan.repeatLogs or chan.repeatLogs[channel].timeout != life:
            chan.repeatLogs[channel] = utils.structures.TimeoutQueue(life)
        patchan = 'pattern%s' % channel
        if self.registryValue('massRepeatPatternLength',channel=channel) > 0:
            if not patchan in chan.repeatLogs or chan.repeatLogs[patchan].timeout != self.registryValue('massRepeatPatternLife',channel=channel):
                chan.repeatLogs[patchan] = utils.structures.TimeoutQueue(self.registryValue('massRepeatPatternLife',channel=channel))
            logs = chan.repeatLogs[patchan]
            for msg in logs:
                if msg in message:
#                       self.log.debug('mass repeat "%s" is found in "%s"' % (msg,message))
                    #self._isSomething(irc,channel,channel,'massRepeat')
                    return True
        logs = chan.repeatLogs[channel]
        trigger = self.registryValue('massRepeatPercent',channel=channel)
        result = False
        flag = False
        pattern = None
        for msg in logs:
            if self._strcompare(message,msg) >= trigger:
                if self.registryValue('massRepeatPatternLength',channel=channel) > 0:
                    pattern = self._largestpattern(message,msg)
                    if pattern and len(pattern) > self.registryValue('massRepeatPatternLength',channel=channel):
                        pattern = pattern
                    else:
                        pattern = None
                flag = True
                break
        if flag:
            result = self._isSomething(irc,channel,channel,'massRepeat')
            if result and pattern:
                if not patchan in chan.repeatLogs or chan.repeatLogs[patchan].timeout != self.registryValue('massRepeatPatternLife',channel=channel):
                    chan.repeatLogs[patchan] = utils.structures.TimeoutQueue(self.registryValue('massRepeatPatternLife',channel=channel))
                chan.repeatLogs[patchan].enqueue(pattern)
        chan.repeatLogs[channel].enqueue(message)
        return result

    def _isCap(self,irc,channel,key,message):
        limit = self.registryValue('capPermit',channel=channel)
        if limit == -1:
            return False
        trigger = self.registryValue('capPercent',channel=channel)
        matchs = self.recaps.findall(message)
        if len(matchs) and len(message):
            percent = len(matchs) / (len(message) * 1.0)
            if percent >= trigger:
                return self._isSomething(irc,channel,key,'cap')
        return False

    def _strcompare (self,a,b):
        # return [0 - 1] ratio between two string
        # jaccard algo
        sa, sb = set(a.lower()), set(b.lower())
        n = len(sa.intersection(sb))
        if float(len(sa) + len(sb) - n) == 0:
            return 0
        jacc = n / float(len(sa) + len(sb) - n)
        return jacc

    def _largestpattern (self,s1,s2):
        s1 = s1.lower()
        s2 = s2.lower()
        m = [[0] * (1 + len(s2)) for i in xrange(1 + len(s1))]
        longest, x_longest = 0, 0
        for x in xrange(1, 1 + len(s1)):
            for y in xrange(1, 1 + len(s2)):
                if s1[x - 1] == s2[y - 1]:
                    m[x][y] = m[x - 1][y - 1] + 1
                    if m[x][y] > longest:
                        longest = m[x][y]
                        x_longest = x
                else:
                    m[x][y] = 0
        return s1[x_longest - longest: x_longest]

    def reset(self):
        self._ircs = ircutils.IrcDict()

    def die(self):
        self._ircs = ircutils.IrcDict()

    def doError (self,irc,msg):
        self._ircs = ircutils.IrcDict()


Class = ChanTracker
