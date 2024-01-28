###
# Copyright (c) 2013, Nicolas Coevoet
# Copyright (c) 2010, Daniel Folkinshteyn - taken some ideas about threading database (MessageParser)
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

import os, re, sqlite3, socket, threading
import collections, random, time
from operator import itemgetter

from ipaddress import ip_address as IPAddress
from ipaddress import ip_network as IPNetwork

from supybot.commands import *
from supybot import utils, ircutils, ircmsgs, ircdb, plugins, callbacks
from supybot import conf, registry, log, schedule, world

from . import server

# due to more kind of pattern checked, increase size
ircutils._hostmaskPatternEqualCache = utils.structures.CacheDict(10000)
cache = utils.structures.CacheDict(10000)


mcidr = re.compile(r'^(\d{1,3}\.){0,3}\d{1,3}/\d{1,2}$')
m6cidr = re.compile(r'^([0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}/\d{1,3}$')


def checkAddressed(irc, text, channel):
    if irc.isChannel(channel):
        if text[0] in str(conf.supybot.reply.whenAddressedBy.chars.get(channel)):
            return True
    elif text[0] in conf.supybot.reply.whenAddressedBy.chars():
        return True
    return False


def isCommand(cbs, args):
    for c in cbs:
        if c.isCommandMethod(args[0]):
            return True
        if args[0] == c.name().lower() and len(args) > 1 \
                and isCommand([c], args[1:]):
            return True
        if isCommand(c.cbs, args):
            return True


def compareString(a, b):
    """return 0 to 1 float percent of similarity (0.85 seems to be a good average)"""
    if a == b:
        return 1
    sa, sb = set(a), set(b)
    n = len(sa.intersection(sb))
    if float(len(sa) + len(sb) - n) == 0:
        return 0
    jacc = n / float(len(sa) + len(sb) - n)
    return jacc


repetr = re.compile(r"(.+?)\1+")


def repetitions(s):
    for match in repetr.finditer(s):
        yield (match.group(1), len(match.group(0))/len(match.group(1)))


def largestString(s1, s2):
    """return largest pattern available in 2 strings"""
    # From https://en.wikibooks.org/wiki/Algorithm_Implementation/Strings/Longest_common_substring#Python2
    # License: CC BY-SA
    m = [[0] * (1 + len(s2)) for i in range(1 + len(s1))]
    longest, x_longest = 0, 0
    for x in range(1, 1 + len(s1)):
        for y in range(1, 1 + len(s2)):
            if s1[x - 1] == s2[y - 1]:
                m[x][y] = m[x - 1][y - 1] + 1
                if m[x][y] > longest:
                    longest = m[x][y]
                    x_longest = x
            else:
                m[x][y] = 0
    return s1[x_longest - longest: x_longest]


def findPattern(text, minimalCount, minimalLength, minimalPercent):
    items = list(repetitions(text))
    size = len(text)
    candidates = []
    for item in items:
        (pattern, count) = item
        percent = (len(pattern) * count) / size
        if len(pattern) > minimalLength:
            if count > minimalCount or percent > minimalPercent:
                candidates.append(pattern)
    candidates.sort(key=len, reverse=True)
    return None if len(candidates) == 0 else candidates[0]


def matchHostmask(pattern, n, resolve):
    # return the matched pattern for Nick
    if not (n.prefix and ircutils.isUserHostmask(n.prefix)):
        return None
    (nick, ident, host) = ircutils.splitHostmask(n.prefix)
    if n.ip is not None and '@' in pattern and n.ip.find('*') == -1 \
            and mcidr.match(pattern.split('@')[1]):
        address = IPAddress('%s' % n.ip)
        try:
            network = IPNetwork(u'%s' % pattern.split('@')[1], strict=False)
            if address in network:
                return '%s!%s@%s' % (nick, ident, n.ip)
        except:
            return None
    elif n.ip is not None and '@' in pattern and n.ip.find('*') == -1 \
            and m6cidr.match(pattern.split('@')[1]):
        address = IPAddress('%s' % n.ip)
        try:
            network = IPNetwork(u'%s' % pattern.split('@')[1], strict=False)
            if address in network:
                return '%s!%s@%s' % (nick, ident, n.ip)
        except:
            return None
    if ircutils.isUserHostmask(pattern):
        if n.ip is not None and ircutils.hostmaskPatternEqual(pattern, '%s!%s@%s' % (
                nick, ident, n.ip)):
            return '%s!%s@%s' % (nick, ident, n.ip)
        if ircutils.hostmaskPatternEqual(pattern, n.prefix):
            return n.prefix
    return None


def matchAccount(pattern, pat, negate, n, extprefix):
    # for $a, $~a, $a: extended pattern
    result = None
    if negate:
        if not len(pat) and n.account is None:
            result = n.prefix
    else:
        if len(pat):
            if n.account is not None and ircutils.hostmaskPatternEqual(
                    '*!*@%s' % pat, '*!*@%s' % n.account):
                result = '%sa:%s' % (extprefix, n.account)
        else:
            if n.account is not None:
                result = '%sa:%s' % (extprefix, n.account)
    return result


def matchRealname(pattern, pat, negate, n, extprefix):
    # for $~r $r: extended pattern
    if n.realname is None:
        return None
    if negate:
        if len(pat) and not ircutils.hostmaskPatternEqual('*!*@%s' % pat, '*!*@%s' % n.realname):
            return '%sr:%s' % (extprefix, n.realname.replace(' ', '?'))
    else:
        if len(pat) and ircutils.hostmaskPatternEqual('*!*@%s' % pat, '*!*@%s' % n.realname):
            return '%sr:%s' % (extprefix, n.realname.replace(' ', '?'))
    return None


def matchGecos(pattern, pat, negate, n, extprefix):
    # for $~x, $x: extended pattern
    if n.realname is None:
        return None
    tests = []
    (nick, ident, host) = ircutils.splitHostmask(n.prefix)
    tests.append(n.prefix)
    if n.ip is not None:
        tests.append('%s!%s@%s' % (nick, ident, n.ip))
    for test in tests:
        test = '%s#%s' % (test, n.realname.replace(' ', '?'))
        if negate:
            if not ircutils.hostmaskPatternEqual(pat, test):
                return test
        else:
            if ircutils.hostmaskPatternEqual(pat, test):
                return test
    return None


def match(pattern, n, irc, resolve):
    if not pattern:
        return None
    if not n.prefix:
        return None
    # check if given pattern match an Nick
    key = '%s :: %s' % (pattern, n)
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
            p = p.split(extprefix)[0]
            #p = p[(p.rfind(extprefix)+1):]
        if t == 'a':
            cache[key] = matchAccount(pattern, p, negate, n, extprefix)
        elif t == 'r':
            cache[key] = matchRealname(pattern, p, negate, n, extprefix)
        elif t == 'x':
            cache[key] = matchGecos(pattern, p, negate, n, extprefix)
        elif t == 'z':
            return None
        else:
            # bug if ipv6 is used..
            k = pattern[(pattern.rfind(':')+1):]
            cache[key] = matchHostmask(k, n, resolve)
    else:
        p = pattern
        if extprefix in p:
            p = p.split(extprefix)[0]
        cache[key] = matchHostmask(p, n, resolve)
    return cache[key]


def getBestPattern(n, irc, useIp=False, resolve=True):
    # return best pattern for a given Nick
    if not (n.prefix and ircutils.isUserHostmask(n.prefix)):
        return []
    match(n.prefix, n, irc, resolve)
    results = []
    (nick, ident, host) = ircutils.splitHostmask(n.prefix)
    if host.startswith(('gateway/tor-sasl/', 'gateway/vpn/', 'user/')) \
            or ident.startswith('~') or (n.realname and
            n.realname.startswith('[https://web.libera.chat]')):
        ident = '*'
    if n.ip is not None:
        if len(n.ip.split(':')) > 4:
            # large ipv6, for now, use the full ipv6
            #a = n.ip.split(':')
            #m = a[0]+':'+a[1]+':'+a[2]+':'+a[3]+':*'
            results.append('*!%s@%s' % (ident, n.ip))
        else:
            if useIp:
                results.append('*!%s@*%s' % (ident, n.ip))
            else:
                results.append('*!%s@%s' % (ident, n.ip))
    if '/' in host:
        # cloaks
        if host.startswith('gateway/'):
            h = host.split('/')
            if 'x-' in host and not 'vpn/' in host:
                # gateway/type/(domain|account) [?/random]
                p = ''
                if len(h) > 3:
                    p = '/*'
                    h = h[:3]
                    host = '%s%s' % ('/'.join(h), p)
        elif host.startswith('nat/'):
            h = host.replace('nat/', '')
            if '/' in h:
                host = 'nat/%s/*' % h.split('/')[0]
    k = '*!%s@%s' % (ident, host)
    if k not in results:
        results.append(k)
    extprefix = ''
    extmodes = ''
    if 'extban' in irc.state.supported:
        ext = irc.state.supported['extban']
        extprefix = ext.split(',')[0]
        extmodes = ext.split(',')[1]
    if n.account:
        results.append('%sa:%s' % (extprefix, n.account))
    if n.realname:
        results.append('%sr:%s' % (extprefix, n.realname.replace(' ', '?')))
    return results


def clearExtendedBanPattern(pattern, irc):
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


def floatToGMT(t):
    f = None
    try:
        f = float(t)
    except:
        return None
    return time.strftime('%Y-%m-%d %H:%M:%S GMT', time.gmtime(f))


class Ircd(object):
    __slots__ = ('irc', 'name', 'channels', 'nicks', 'queue',
                 'lowQueue', 'logsSize', 'askedItems', 'whoxpending')
    # define an ircd, keeps Chan and Nick items

    def __init__(self, irc, logsSize):
        object.__init__(self)
        self.irc = irc
        self.name = irc.network
        self.channels = ircutils.IrcDict()
        self.nicks = ircutils.IrcDict()
        # contains IrcMsg, kicks, modes, etc
        self.queue = utils.structures.smallqueue()
        # contains less important IrcMsgs (sync, logChannel)
        self.lowQueue = utils.structures.smallqueue()
        self.logsSize = logsSize
        self.whoxpending = False
        self.askedItems = {}

    def getChan(self, irc, channel):
        if not (channel and irc):
            return None
        self.irc = irc
        if channel not in self.channels:
            self.channels[channel] = Chan(self, channel)
        return self.channels[channel]

    def getNick(self, irc, nick, raw=False):
        if not (nick and irc):
            return None
        self.irc = irc
        if nick not in self.nicks:
            self.nicks[nick] = Nick(self.logsSize)
        if not (self.nicks[nick].prefix or raw):
            try:
                self.nicks[nick].setPrefix(irc.state.nickToHostmask(nick))
            except:
                pass
        return self.nicks[nick]

    def getItem(self, irc, uid):
        # return active item
        if not (irc and uid):
            return None
        for channel in list(self.channels.keys()):
            chan = self.getChan(irc, channel)
            items = chan.getItems()
            for type in list(items.keys()):
                for value in items[type]:
                    item = items[type][value]
                    if item.uid == uid:
                        return item
        # TODO: maybe uid under modes that need op to be shown ?
        return None

    def info(self, irc, uid, prefix, db):
        # return mode changes summary
        if not (uid and prefix):
            return []
        c = db.cursor()
        c.execute("""SELECT channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by
                     FROM bans WHERE id=? LIMIT 1""", (uid,))
        L = c.fetchall()
        if not len(L):
            c.close()
            return []
        (channel, oper, kind, mask, begin_at, end_at, removed_at, removed_by) = L[0]
        if not ircdb.checkCapability(prefix, '%s,op' % channel):
            c.close()
            return []
        results = []
        current = time.time()
        results.append([channel, '[%s] [%s] %s sets +%s %s' % (
            channel, floatToGMT(begin_at), oper, kind, mask)])
        if not removed_at:
            if begin_at == end_at:
                results.append([channel, 'is set forever'])
            else:
                s = 'set for %s,' % utils.timeElapsed(end_at-begin_at)
                remaining = end_at - current
                if remaining >= 0:
                    s += ' with %s more,' % utils.timeElapsed(remaining)
                    s += ' and ends at [%s]' % floatToGMT(end_at)
                else:
                    s += ' expired %s,' % utils.timeElapsed(remaining)
                    s += ' and ended at [%s]' % floatToGMT(end_at)
                results.append([channel, s])
        else:
            s = 'was active %s and ended on [%s]' % (
                utils.timeElapsed(removed_at-begin_at), floatToGMT(removed_at))
            if end_at != begin_at:
                s += ', initially for %s' % utils.timeElapsed(end_at-begin_at)
            s += ', removed by %s' % removed_by
            results.append([channel, s])
        c.execute("""SELECT oper,comment FROM comments WHERE ban_id=?""", (uid,))
        L = c.fetchall()
        if len(L):
            for com in L:
                (oper, comment) = com
                results.append([channel,'"%s" by %s' % (comment, oper)])
        c.execute("""SELECT full,log FROM nicks WHERE ban_id=?""", (uid,))
        L = c.fetchall()
        if len(L) == 1:
            for affected in L:
                (full, log) = affected
                message = ""
                for line in log.split('\n'):
                    message = '%s' % line
                    break
                results.append([channel,message])
        elif len(L) > 1:
            results.append([channel,'affects %s users' % len(L)])
#        if len(L):
#            for affected in L:
#                (full, log) = affected
#                message = full
#                for line in log.split('\n'):
#                    message = '[%s]' % line
#                    break
#                results.append(message)
        c.close()
        return results

    def pending(self, irc, channel, mode, prefix, pattern, db, never, ids, duration):
        # returns active items for a channel mode
        if not (channel and mode and prefix):
            return []
        chan = self.getChan(irc, channel)
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
                            r.append([item.uid, item.mode, item.value,
                                item.by, item.when, item.expire])
                    else:
                        if duration > 0:
                            #log.debug('%s -> %s : %s' % (duration,item.when,(t-item.when)))
                            if (t - item.when) > duration:
                                r.append([item.uid, item.mode, item.value,
                                    item.by, item.when, item.expire])
                        else:
                            r.append([item.uid, item.mode, item.value,
                                item.by, item.when, item.expire])
        r.sort(reverse=True)
        if len(r):
            for item in r:
                (uid, mode, value, by, when, expire) = item
                if not (pattern is None or ircutils.hostmaskPatternEqual(pattern, by)):
                    continue
                c.execute("""SELECT oper,comment FROM comments WHERE ban_id=?
                             ORDER BY at DESC LIMIT 1""", (uid,))
                L = c.fetchall()
                if len(L):
                    (oper, comment) = L[0]
                    message = ' "%s"' % comment
                else:
                    message = ''
                if ids:
                    results.append('%s' % uid)
                elif expire and expire != when:
                    results.append('[#%s +%s %s by %s expires at %s]%s' % (
                        uid, mode, value, by, floatToGMT(expire), message))
                else:
                    results.append('[#%s +%s %s by %s on %s]%s' % (
                        uid, mode, value, by, floatToGMT(when), message))
        c.close()
        return results

    def against(self, irc, channel, n, prefix, db, ct):
        # returns active items that match n
        if not (channel and n and db):
            return []
        chan = self.getChan(irc, channel)
        results = []
        r = []
        c = db.cursor()
        channels = []
        for k in list(chan.getItems()):
            items = chan.getItemsFor(k)
            if len(items):
                for item in items:
                    item = items[item]
                    if match(item.value, n, irc, ct.registryValue('resolveIp')):
                        r.append([item.uid, item.mode, item.value,
                            item.by, item.when, item.expire])
                    elif item.value.find('$j:') == 0:
                        channels.append(item.value.replace('$j:', ''))
        if len(channels):
            for ch in channels:
                cha = self.getChan(irc, ch)
                for k in list(cha.getItems()):
                    items = cha.getItemsFor(k)
                    if len(items):
                        for item in items:
                            item = items[item]
                            if match(item.value, n, irc, ct.registryValue('resolveIp')):
                                r.append([item.uid, item.mode, item.value,
                                    item.by, item.when, item.expire])
        r.sort(reverse=True)
        if len(r):
            for item in r:
                (uid, mode, value, by, when, expire) = item
                c.execute("""SELECT oper,comment FROM comments WHERE ban_id=?
                             ORDER BY at DESC LIMIT 1""", (uid,))
                L = c.fetchall()
                if len(L):
                    (oper, comment) = L[0]
                    message = ' "%s"' % comment
                else:
                    message = ''
                if expire and expire != when:
                    results.append('[#%s +%s %s by %s expires at %s]%s' % (
                        uid, mode, value, by, floatToGMT(expire), message))
                else:
                    results.append('[#%s +%s %s by %s on %s]%s' % (
                        uid, mode, value, by, floatToGMT(when), message))
        c.close()
        return results

    def log(self, irc, uid, prefix, db):
        # return log of users affected by a mode change
        if not (uid and prefix):
            return []
        c = db.cursor()
        c.execute("""SELECT channel FROM bans WHERE id=?""", (uid,))
        L = c.fetchall()
        if not len(L):
            c.close()
            return []
        (channel,) = L[0]
        if not ircdb.checkCapability(prefix, '%s,op' % channel):
            c.close()
            return []
        results = []
#        c.execute("""SELECT oper,comment,at FROM comments WHERE ban_id=?
#                     ORDER BY at DESC""", (uid,))
#        L = c.fetchall()
#        if len(L):
#            for com in L:
#                (oper, comment, at) = com
#                results.append('"%s" by %s on %s' % (comment, oper, floatToGMT(at)))
        c.execute("""SELECT full,log FROM nicks WHERE ban_id=?""", (uid,))
        L = c.fetchall()
        if len(L):
            for item in L:
                (full, log) = item
                results.append('For [%s]' % full)
                for line in log.split('\n'):
                    results.append(line)
        else:
            results.append('no log found')
        c.close()
        return results

    def search(self, irc, pattern, prefix, db, deep, active, never, channel, ids):
        # deep search inside database,
        # results filtered depending prefix capability
        c = db.cursor()
        bans = set([])
        results = []
        isOwner = ircdb.checkCapability(prefix, 'owner') or prefix == irc.prefix
        glob = '*%s*' % pattern
        like = '%%%s%%' % pattern
        if pattern.startswith('$'):
            pattern = clearExtendedBanPattern(pattern, irc)
            glob = '*%s*' % pattern
            like = '%%%s%%' % pattern
        elif ircutils.isUserHostmask(pattern):
            (n, i, h) = ircutils.splitHostmask(pattern)
            if n == '*':
                n = None
            if i == '*':
                i = None
            if h == '*':
                h = None
            items = [n, i, h]
            subpattern = ''
            for item in items:
                if item:
                    subpattern += '*%s' % item
            glob = '*%s*' % subpattern
            like = '%%%s%%' % subpattern
            c.execute("""SELECT id,mask FROM bans ORDER BY id DESC""")
            items = c.fetchall()
            if len(items):
                for item in items:
                    (uid, mask) = item
                    if ircutils.hostmaskPatternEqual(pattern, mask):
                        bans.add(uid)
            c.execute("""SELECT ban_id,full FROM nicks ORDER BY ban_id DESC""")
            items = c.fetchall()
            if len(items):
                for item in items:
                    (uid, full) = item
                    if ircutils.hostmaskPatternEqual(pattern, full):
                        bans.add(uid)
        if deep:
            c.execute("""SELECT ban_id,full FROM nicks WHERE full GLOB ? OR full LIKE ?
                         OR log GLOB ? OR log LIKE ? ORDER BY ban_id DESC""", (glob, like, glob, like))
        else:
            c.execute("""SELECT ban_id,full FROM nicks WHERE full GLOB ? OR full LIKE ?
                         ORDER BY ban_id DESC""", (glob, like))
        items = c.fetchall()
        if len(items):
            for item in items:
                (uid, full) = item
                bans.add(uid)
        c.execute("""SELECT id,mask FROM bans WHERE mask GLOB ? OR mask LIKE ?
                     ORDER BY id DESC""", (glob, like))
        items = c.fetchall()
        if len(items):
            for item in items:
                (uid, mask) = item
                bans.add(uid)
        c.execute("""SELECT ban_id,comment FROM comments WHERE comment GLOB ? OR comment LIKE ?
                     ORDER BY ban_id DESC""", (glob, like))
        items = c.fetchall()
        if len(items):
            for item in items:
                (uid, comment) = item
                bans.add(uid)
        if len(bans):
            for uid in bans:
                c.execute("""SELECT id,mask,kind,channel,begin_at,end_at,removed_at
                             FROM bans WHERE id=? ORDER BY id DESC LIMIT 1""", (uid,))
                items = c.fetchall()
                for item in items:
                    (uid, mask, kind, chan, begin_at, end_at, removed_at) = item
                    if isOwner or ircdb.checkCapability(prefix, '%s,op' % chan):
                        if (never or active) and removed_at:
                            continue
                        if never and begin_at != end_at:
                            continue
                        if channel and chan != channel:
                            continue
                        results.append([uid, mask, kind, chan])
        if len(results):
            results.sort(reverse=True)
            i = 0
            msgs = []
            while i < len(results):
                (uid, mask, kind, chan) = results[i]
                if ids:
                    msgs.append('%s' % uid)
                elif channel and len(channel):
                    msgs.append('[#%s +%s %s]' % (uid, kind, mask))
                else:
                    msgs.append('[#%s +%s %s in %s]' % (uid, kind, mask, chan))
                i += 1
            c.close()
            return msgs
        c.close()
        return []

    def affect(self, irc, uid, prefix, db):
        # return users affected by a mode change
        if not (uid and prefix):
            return []
        c = db.cursor()
        c.execute("""SELECT channel FROM bans WHERE id=?""", (uid,))
        L = c.fetchall()
        if not len(L):
            c.close()
            return []
        (channel,) = L[0]
        if not ircdb.checkCapability(prefix, '%s,op' % channel):
            c.close()
            return []
        results = []
        c.execute("""SELECT full,log FROM nicks WHERE ban_id=?""", (uid,))
        L = c.fetchall()
        if len(L):
            for item in L:
                (full, log) = item
                message = full
                for line in log.split('\n'):
                    message = '[%s]' % line
                    break
                results.append(message)
        else:
            results.append('nobody affected')
        c.close()
        return results

    def markremoved(self, irc, uid, message, prefix, db, ct):
        # won't use channel,mode,value, because Item may be removed already
        # it's a duplicate of mark, only used to compute logChannel on a removed item
        if not (prefix and message):
            return False
        c = db.cursor()
        c.execute("""SELECT id,channel,kind,mask FROM bans WHERE id=?""", (uid,))
        L = c.fetchall()
        b = False
        if len(L):
            (uid, channel, kind, mask) = L[0]
            if not (ircdb.checkCapability(prefix, '%s,op' % channel)
                    or prefix == irc.prefix):
                c.close()
                return False
            current = time.time()
            c.execute("""INSERT INTO comments VALUES (?, ?, ?, ?)""", (uid, prefix, current, message))
            db.commit()
            f = None
            if (prefix != irc.prefix and ct.registryValue('announceMark', channel=channel, network=irc.network)) \
                    or (prefix == irc.prefix and ct.registryValue('announceBotMark', channel=channel, network=irc.network)):
                f = ct._logChan
            if f:
                if ct.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                    f(irc, channel, '[%s] [#%s %s %s] marked by %s: %s' % (
                        ircutils.bold(channel), ircutils.mircColor(uid, 'yellow', 'black'),
                        ircutils.bold(ircutils.mircColor('+%s' % kind, 'red')),
                        ircutils.mircColor(mask, 'light blue'), prefix.split('!')[0], message))
                else:
                    f(irc, channel, '[%s] [#%s +%s %s] marked by %s: %s' % (
                        channel, uid, kind, mask, prefix.split('!')[0], message))
            b = True
        c.close()
        return b

    def mark(self, irc, uid, message, prefix, db, logFunction, ct):
        # won't use channel,mode,value, because Item may be removed already
        if not (prefix and message):
            return False
        c = db.cursor()
        c.execute("""SELECT id,channel,kind,mask FROM bans WHERE id=?""", (uid,))
        L = c.fetchall()
        b = False
        if len(L):
            (uid, channel, kind, mask) = L[0]
            if not (ircdb.checkCapability(prefix, '%s,op' % channel)
                    or prefix == irc.prefix):
                c.close()
                return False
            current = time.time()
            c.execute("""INSERT INTO comments VALUES (?, ?, ?, ?)""", (uid, prefix, current, message))
            db.commit()
            if logFunction:
                key = '%s|%s' % (kind, mask)
                if key in ct.smartLog and ct.smartLog[key]:
                    if 'edited by' in ct.smartLog[key][-1]:
                        message = 'and marked: %s' % message
                    else:
                        message = 'marked by %s: %s' % (prefix.split('!')[0], message)
                    message = '; '.join(ct.smartLog[key] + [message])
                    del ct.smartLog[key]
                elif ct.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                    message = '[%s] [#%s %s %s] marked by %s: %s' % (
                        ircutils.bold(channel), ircutils.mircColor(uid, 'yellow', 'black'),
                        ircutils.bold(ircutils.mircColor('+%s' % kind, 'red')),
                        ircutils.mircColor(mask, 'light blue'), prefix.split('!')[0], message)
                else:
                    message = '[%s] [#%s +%s %s] marked by %s: %s' % (
                        channel, uid, kind, mask, prefix.split('!')[0], message)
                logFunction(irc, channel, message)
            b = True
        c.close()
        return b

    def submark(self, irc, channel, mode, value, message, prefix, db, logFunction, ct):
        # add mark to an item that is not already in lists
        if not (channel and mode and value and prefix):
            return False
        if not (ircdb.checkCapability(prefix, '%s,op' % channel)
                or prefix == irc.prefix):
            return False
        c = db.cursor()
        c.execute("""SELECT id,oper FROM bans WHERE channel=? AND kind=? AND mask=?
                     AND removed_at is NULL ORDER BY id LIMIT 1""", (channel, mode, value))
        L = c.fetchall()
        c.close()
        if len(L):
            # item exists
            (uid, oper) = L[0]
            # should not happen, but..
            return self.mark(irc, uid, message, prefix, db, logFunction, ct)
        elif channel in self.channels:
            chan = self.getChan(irc, channel)
            item = chan.getItem(mode, value)
            if not item:
                # prepare item update after being set (we don't have id yet)
                key = '%s|%s' % (mode, value)
                chan.mark[key] = [mode, value, message, prefix]
                return True
        return False

    def add(self, irc, channel, mode, value, seconds, autoexpire, prefix, db):
        # add new eIqb item
        if channel not in self.channels:
            return False
        if not (channel and mode and value and prefix):
            return False
        if not (ircdb.checkCapability(prefix, '%s,op' % channel)
                or prefix == irc.prefix):
            return False
        c = db.cursor()
        c.execute("""SELECT id,oper FROM bans WHERE channel=? AND kind=? AND mask=?
                     AND removed_at is NULL ORDER BY id LIMIT 1""", (channel, mode, value))
        L = c.fetchall()
        c.close()
        chan = self.getChan(irc, channel)
        # prepare item update after being set (we don't have id yet)
        key = '%s|%s' % (mode, value)
        if seconds is not None:
            chan.update[key] = [mode, value, seconds, prefix]
        else:
            chan.update[key] = [mode, value, autoexpire, irc.prefix]
        if not len(L):
            # enqueue mode changes
            chan.queue.enqueue(('+%s' % mode, value))
        return True

    def remove(self, uid, db):
        c = db.cursor()
        c.execute("""SELECT id,channel,kind,mask FROM bans WHERE id=? LIMIT 1""", (uid,))
        L = c.fetchall()
        if len(L):
            c.execute("""DELETE FROM bans WHERE id=? LIMIT 1""", (uid,))
            c.execute("""DELETE FROM comments WHERE ban_id=?""", (uid,))
            c.execute("""DELETE FROM nicks WHERE ban_id=?""", (uid,))
            db.commit()
            c.close()
            return True
        c.close()
        return False

    def edit(self, irc, channel, mode, value, seconds, prefix, db, scheduleFunction, logFunction, ct):
        # edit eIqb duration
        if not (channel and mode and value and prefix):
            return False
        if not (ircdb.checkCapability(prefix, '%s,op' % channel)
                or prefix == irc.prefix):
            return False
        c = db.cursor()
        c.execute("""SELECT id,channel,kind,mask,begin_at,end_at FROM bans WHERE channel=? AND kind=?
                     AND mask=? AND removed_at is NULL ORDER BY id LIMIT 1""", (channel, mode, value))
        L = c.fetchall()
        b = False
        if len(L):
            (uid, channel, kind, mask, begin_at, end_at) = L[0]
            chan = self.getChan(irc, channel)
            current = time.time()
            if begin_at == end_at:
                if seconds < 0:
                    c.close()
                    return True
                text = 'was set forever'
            else:
                text = 'ended [%s] for %s' % (
                    floatToGMT(end_at), utils.timeElapsed(end_at-begin_at))
            if seconds < 0:
                newEnd = begin_at
                expires = 'expires never'
            elif seconds == 0:
                newEnd = current  # force expires on next tickle
                expires = 'expires at [%s], for %s in total' % (
                    floatToGMT(newEnd), utils.timeElapsed(newEnd-begin_at))
            else:
                newEnd = current + seconds
                expires = 'expires at [%s], for %s in total' % (
                    floatToGMT(newEnd), utils.timeElapsed(newEnd-begin_at))
            text = '%s, now %s' % (text, expires)
            c.execute("""INSERT INTO comments VALUES (?, ?, ?, ?)""", (uid, prefix, current, text))
            c.execute("""UPDATE bans SET end_at=? WHERE id=?""", (newEnd, int(uid)))
            db.commit()
            i = chan.getItem(kind, mask)
            if i:
                if newEnd == begin_at:
                    i.expire = None
                else:
                    i.expire = newEnd
                    if scheduleFunction and newEnd != current:
                        scheduleFunction(irc, newEnd, prefix != irc.prefix)
            if logFunction:
                key = '%s|%s' % (kind, mask)
                if key in ct.smartLog and ct.smartLog[key]:
                    message = 'edited by %s: %s' % (prefix.split('!')[0], expires)
                elif ct.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                    message = '[%s] [#%s %s %s] edited by %s: %s' % (
                        ircutils.bold(channel), ircutils.mircColor(uid, 'yellow', 'black'),
                        ircutils.bold(ircutils.mircColor('+%s' % kind, 'red')),
                        ircutils.mircColor(mask, 'light blue'), prefix.split('!')[0], expires)
                else:
                    message = '[%s] [#%s +%s %s] edited by %s: %s' % (
                        channel, uid, kind, mask, prefix.split('!')[0], expires)
                if key in ct.smartLog:
                    ct.smartLog[key].append(message)
                else:
                    logFunction(irc, channel, message)
            b = True
        c.close()
        return b

    def resync(self, irc, channel, mode, db, logFunction, ct):
        # sync mode lists; if items were removed when bot was offline, mark records as removed
        c = db.cursor()
        c.execute("""SELECT id,channel,mask FROM bans WHERE channel=? AND kind=?
                     AND removed_at is NULL ORDER BY id""", (channel, mode))
        L = c.fetchall()
        current = time.time()
        commits = 0
        msgs = []
        if len(L):
            current = time.time()
            if channel in irc.state.channels:
                chan = self.getChan(irc, channel)
                if mode in chan.dones:
                    for record in L:
                        (uid, channel, mask) = record
                        item = chan.getItem(mode, mask)
                        if not item:
                            c.execute("""UPDATE bans SET removed_at=?, removed_by=? WHERE id=?""",
                                (current, 'offline!offline@offline', int(uid)))
                            commits += 1
                            if ct.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                                msgs.append('[#%s %s]' % (ircutils.mircColor(uid, 'yellow', 'black'),
                                    ircutils.mircColor(mask, 'light blue')))
                            else:
                                msgs.append('[#%s %s]' % (uid, mask))
                            self.verifyRemoval(irc, channel, mode, mask, db, ct, uid)
        if commits > 0:
            db.commit()
            if logFunction:
                if ct.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                    logFunction(irc, channel, '[%s] [%s] %s removed: %s' % (ircutils.bold(
                        channel), ircutils.bold(ircutils.mircColor(mode, 'green')),
                        commits, ' '.join(msgs)))
                else:
                    logFunction(irc, channel, '[%s] [%s] %s removed: %s' % (
                        channel, mode, commits, ' '.join(msgs)))
        # TODO: restore patterns
        c.execute("""SELECT id,pattern,regexp,trigger,life,mode,duration
                     FROM patterns WHERE channel=? ORDER BY id""", (channel,))
        L = c.fetchall()
        if len(L):
            if channel in irc.state.channels:
                chan = self.getChan(irc, channel)
                for record in L:
                    (uid, pattern, regexp, trigger, life, mode, duration) = record
                    chan.patterns[uid] = Pattern(uid, pattern,
                        int(regexp) == 1, trigger, life, mode, duration)
        c.close()

    def verifyRemoval (self, irc, channel, mode, value, db, ct, uid):
        if ct.registryValue('autoRemoveUnregisteredQuiets', channel=channel, network=irc.network) and mode == 'q' and value == '$~a':
            self.remove(uid, db)


class Chan(object):
    __slots__ = ('ircd', 'name', '_lists', 'queue', 'update', 'mark', 'action', 'dones', 'syn', 'opAsked',
                 'deopAsked', 'deopPending', 'spam', 'repeatLogs', 'nicks', 'netsplit', 'attacked', 'patterns')
    # in memory and in database stores +eIqb list -ov
    # no user action from here, only ircd messages

    def __init__(self, ircd, name):
        object.__init__(self)
        self.ircd = ircd
        self.name = name
        self._lists = ircutils.IrcDict()
        # queue contains (mode,valueOrNone) - ircutils.joinModes
        self.queue = utils.structures.smallqueue()
        # contains [mode|value] = [mode,value,seconds,prefix]
        self.update = ircutils.IrcDict()
        # contains [mode|value] = [mode,value,message,prefix]
        self.mark = ircutils.IrcDict()
        # contains IrcMsg (mostly kick/fpart)
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

    def isWrong(self, pattern):
        if 'bad' in self.spam and pattern in self.spam['bad']:
            if len(self.spam['bad'][pattern]) > 0:
                return True
        return False

    def getItems(self):
        # [X][Item.value] is Item
        return self._lists

    def getItemsFor(self, mode):
        if mode not in self._lists:
            self._lists[mode] = ircutils.IrcDict()
        return self._lists[mode]

    def summary(self, db):
        r = ['For %s' % self.name, 'Format: active/total']
        c = db.cursor()
        c.execute("""SELECT id,oper,kind,removed_at FROM bans WHERE channel=?""", (self.name,))
        L = c.fetchall()
        total = {}
        opers = {}
        if len(L):
            for item in L:
                (uid, oper, kind, removed_at) = item
                if kind not in total:
                    total[kind] = {}
                    total[kind]['active'] = 0
                    total[kind]['removed'] = 0
                if not removed_at:
                    total[kind]['active'] += 1
                else:
                    total[kind]['removed'] += 1
                if oper not in opers:
                    opers[oper] = {}
                if kind not in opers[oper]:
                    opers[oper][kind] = {}
                    opers[oper][kind]['active'] = 0
                    opers[oper][kind]['removed'] = 0
                if not removed_at:
                    opers[oper][kind]['active'] += 1
                else:
                    opers[oper][kind]['removed'] += 1
            modes = []
            for kind in total:
                modes.append('%s/%s %s' % (total[kind]['active'],
                    total[kind]['active']+total[kind]['removed'], kind))
            r.append(', '.join(modes))
            for oper in opers:
                modes = []
                modes.append('%s:' % oper)
                for kind in opers[oper]:
                    modes.append('%s/%s %s' % (opers[oper][kind]['active'],
                        opers[oper][kind]['active']+opers[oper][kind]['removed'], kind))
                r.append(', '.join(modes))
        c.close()
        return r

    def addItem(self, mode, value, by, when, db, checkUser=True, ct=None):
        # eqIb(+*) (-ov) pattern prefix when
        # mode: eqIb -ov + ?
        if mode != 'm':
            l = self.getItemsFor(mode)
        else:
            l = {}
        if not self.syn:
            checkUser = False
        if value not in l:
            i = Item()
            i.channel = self.name
            i.mode = mode
            i.value = value
            uid = None
            expire = when
            c = db.cursor()
            c.execute("""SELECT id,oper,begin_at,end_at FROM bans WHERE channel=? AND kind=? AND mask=?
                         AND removed_at is NULL ORDER BY id LIMIT 1""", (self.name, mode, value))
            L = c.fetchall()
            if len(L):
                # restoring stored informations, due to netsplit server's values may be wrong
                (uid, by, when, expire) = L[0]
                c.execute("""SELECT ban_id,full FROM nicks WHERE ban_id=?""", (uid,))
                L = c.fetchall()
                i.isNew = False
                if len(L):
                    for item in L:
                        (uid, full) = item
                        i.affects.append(full)
            else:
                # if begin_at == end_at --> that means forever
                c.execute("""INSERT INTO bans VALUES (NULL, ?, ?, ?, ?, ?, ?, NULL, NULL)""",
                    (self.name, by, mode, value, when, when))
                i.isNew = True
                uid = c.lastrowid
                # leave channel user list management to supybot
                ns = []
                if self.name in self.ircd.irc.state.channels and checkUser:
                    for nick in list(self.ircd.irc.state.channels[self.name].users):
                        n = self.ircd.getNick(self.ircd.irc, nick)
                        m = match(value, n, self.ircd.irc, ct.registryValue('resolveIp'))
                        if m:
                            i.affects.append(n.prefix)
                            # insert logs
                            logs = ['%s' % n]
                            for line in n.logs:
                                (ts, target, message) = line
                                if target in (self.name, 'ALL'):
                                    logs.append('[%s] <%s> %s' % (floatToGMT(ts), nick, message))
                            c.execute("""INSERT INTO nicks VALUES (?, ?, ?, ?)""",
                                (uid, value, n.prefix, '\n'.join(logs)))
                            ns.append([n, m])
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

    def getItem(self, mode, value):
        if mode in self._lists:
            if value in self._lists[mode]:
                return self._lists[mode][value]
        return None

    def removeItem(self, mode, value, by, c):
        # flag item as removed in database, we use a cursor as argument
        # because otherwise database tends to be locked
        removed_at = time.time()
        i = self.getItem(mode, value)
        created = False
        if not i:
            c.execute("""SELECT id,oper,begin_at,end_at FROM bans WHERE channel=? AND kind=? AND mask=?
                         AND removed_at is NULL ORDER BY id LIMIT 1""", (self.name, mode, value))
            L = c.fetchall()
            if len(L):
                (uid, by, when, expire) = L[0]
                i = Item()
                i.uid = uid
                i.mode = mode
                i.value = value
                i.channel = self.name
                i.by = by
                i.when = float(when)
                i.expire = float(expire)
        if i:
            c.execute("""UPDATE bans SET removed_at=?, removed_by=? WHERE id=?""",
                (removed_at, by, int(i.uid)))
            i.removed_by = by
            i.removed_at = removed_at
            del self._lists[mode][value]
        return i

    def addpattern(self, prefix, limit, life, mode, duration, pattern, regexp, db):
        c = db.cursor()
        c.execute("""INSERT INTO patterns VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (self.name, prefix, time.time(), pattern, regexp, limit, life, mode, duration))
        uid = c.lastrowid
        self.patterns[uid] = Pattern(uid, pattern, regexp == 1, limit, life, mode, duration)
        db.commit()
        c.close()
        r = ''
        if regexp == 1:
            r = ' *'
        return '[#%s "%s"%s]' % (uid, pattern, r)

    def rmpattern(self, prefix, uid, db):
        c = db.cursor()
        c.execute("""SELECT id,channel,pattern,regexp FROM patterns
                     WHERE id=? and channel=? LIMIT 1""", (uid, self.name))
        items = c.fetchall()
        if len(items):
            (rid, channel, pattern, regexp) = items[0]
            c.execute("""DELETE FROM patterns WHERE id=? and channel=? LIMIT 1""", (uid, self.name))
            if uid in self.patterns:
                del self.patterns[uid]
            prop = 'Pattern%s' % rid
            if prop in self.spam:
                del self.spam[prop]
            db.commit()
            c.close()
            r = ''
            if regexp == 1:
                r = ' *'
            return '[#%s "%s"%s]' % (uid, pattern, r)
        c.close()
        return False

    def countpattern(self, uid, db):
        c = db.cursor()
        c.execute("""SELECT id,count FROM patterns WHERE id=? and channel=? LIMIT 1""", (uid, self.name))
        items = c.fetchall()
        (rid, count) = items[0]
        c.execute("""UPDATE patterns SET count=? WHERE id=?""", (int(count)+1, uid))
        db.commit()
        c.close()

    def lspattern(self, prefix, pattern, db):
        c = db.cursor()
        results = []
        items = []
        if pattern:
            i = None
            try:
                i = int(pattern)
            except:
                pass
            if i:
                c.execute("""SELECT id,channel,pattern,oper,at,trigger,life,mode,duration,count,regexp
                             FROM patterns WHERE id=? AND channel=? LIMIT 1""", (i, self.name))
                items = c.fetchall()
                if len(items):
                    (uid, channel, pattern, oper, at, limit, life, mode, duration, count, regexp) = items[0]
                    r = ''
                    if regexp == 1:
                        r = ' *'
                    results.append('[#%s by %s on %s (%s calls) %s/%ss -> %s for %ss: "%s"%s]' % (
                        uid, oper, floatToGMT(at), count, limit, life, mode, duration, pattern, r))
                    items = []
            else:
                glob = '*%s*' % pattern
                like = '%%%s%%' % pattern
                c.execute("""SELECT id,channel,pattern,oper,at,trigger,life,mode,duration,count,regexp
                             FROM patterns WHERE (pattern GLOB ? or pattern LIKE ?) AND channel=?
                             ORDER BY id DESC""", (glob, like, self.name))
                items = c.fetchall()
        else:
            c.execute("""SELECT id,channel,pattern,oper,at,trigger,life,mode,duration,count,regexp
                         FROM patterns WHERE channel=? ORDER BY id DESC""", (self.name,))
            items = c.fetchall()
        if len(items):
            for item in items:
                (uid, channel, pattern, oper, at, limit, life, mode, duration, count, regexp) = item
                r = ''
                if regexp == 1:
                    r = ' *'
                results.append('[#%s (%s calls) %s/%ss -> %s for %ss: "%s"%s]' % (
                    uid, count, limit, life, mode, duration, pattern, r))
        return results


class Item(object):
    __slots__ = ('channel', 'mode', 'value', 'by', 'when', 'uid',
                 'expire', 'removed_at', 'removed_by', 'asked', 'affects', 'isNew')

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
        return 'Item(%s [%s][%s] by %s on %s, expire on %s, removed on %s by %s)' % (
            self.uid, self.mode, self.value, self.by, floatToGMT(self.when),
            floatToGMT(end), floatToGMT(self.removed_at), self.removed_by)


class Nick(object):
    __slots__ = ('prefix', 'ip', 'realname', 'account', 'logSize', 'logs')

    def __init__(self, logSize):
        object.__init__(self)
        self.prefix = None
        self.ip = None
        self.realname = None
        self.account = None
        self.logSize = logSize
        self.logs = []
        # log format:
        # target can be a channel, or 'ALL' when it's related to nick itself
        # (account changes, nick changes, host changes, etc)
        # [float(timestamp),target,message]

    def setPrefix(self, prefix):
        if self.prefix != prefix:
            self.ip = None
        self.prefix = prefix
        return self

    def setIp(self, ip):
        if not (ip == self.ip or ip == '255.255.255.255') and utils.net.isIP(ip):
            self.ip = ip
        return self

    def setAccount(self, account):
        if account == '*':
            account = None
        self.account = account
        return self

    def setRealname(self, realname):
        self.realname = realname
        return self

    def addLog(self, target, message):
        if len(self.logs) == self.logSize:
            del self.logs[0]
        self.logs.append([time.time(), target, message])
        return self

    def __repr__(self):
        ip = self.ip
        if ip is None:
            ip = '(n/a)'
        account = self.account
        if account is None:
            account = '(n/a)'
        realname = self.realname
        if realname is None:
            realname = '(n/a)'
        return '%s ip:%s account:%s username:%s' % (self.prefix, ip, account, realname)


class Pattern(object):
    __slots__ = ('uid', 'pattern', 'regexp', 'limit',
                 'life', 'mode', 'duration', '_match')

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

    def match(self, text):
        if self._match:
            tmp = self._match.search(text)
            if tmp is not None:
                return (True, tmp.group(0))
            else:
                return (False, None)
        if self.pattern in text:
            return (True, self.pattern)
        return (False, None)


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
                s += ' %s' % args.pop(0)
            if len(s) < 512:
                state.args.append([s, f(s)])
            else:
                state.errorInvalid('regular expression', s)
        except IndexError:
            args[:] = original
            state.errorInvalid('regular expression', s)
    return get


getPatternAndMatcher = _getRe(utils.str.perlReToPythonRe)
addConverter('getPatternAndMatcher', getPatternAndMatcher)


# Taken from plugins.Time.seconds
_SECONDS_RE = re.compile(r'-?[0-9]+[ywdhms]')
def getTs(irc, msg, args, state):
    seconds = None
    secs = _SECONDS_RE.findall(args[0])
    for sec in secs:
        (i, kind) = int(sec[:-1]), sec[-1]
        if seconds is None:
            seconds = 0
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
    if seconds is None:
        raise callbacks.ArgumentError
    del args[0]
    state.args.append(float(seconds))


addConverter('getTs', getTs)


def getProba(irc, msg, args, state):
    try:
        v = float(args[0])
        if v < 0 or v > 1:
            raise callbacks.ArgumentError
        state.args.append(v)
        del args[0]
    except ValueError:
        raise callbacks.ArgumentError


addConverter('proba', getProba)


def getDuration(seconds):
    if not len(seconds):
        return None
    return sum(seconds)


def getWrapper(name):
    parts = registry.split(name)
    group = getattr(conf, parts.pop(0))
    while parts:
        try:
            group = group.get(parts.pop(0))
        except (registry.NonExistentRegistryEntry, registry.InvalidRegistryName):
            raise registry.InvalidRegistryName(name)
    return group


def listGroup(group):
    L = []
    for (vname, v) in group._children.items():
        if hasattr(group, 'channelValue') and group.channelValue and \
                ircutils.isChannel(vname) and not v._children:
            continue
        if hasattr(v, 'channelValue') and v.channelValue:
            L.append(vname)
        utils.sortBy(str.lower, L)
    return L


class ChanTracker(callbacks.Plugin, plugins.ChannelDBHandler):
    """This plugin keeps records of channel mode changes and permits to manage them over time,
    it also has some channel protection features.
    """
    threaded = True
    noIgnore = True

    def __init__(self, irc):
        self.__parent = super(ChanTracker, self)
        self.__parent.__init__(irc)
        callbacks.Plugin.__init__(self, irc)
        plugins.ChannelDBHandler.__init__(self)
        self.lastTickle = None
        self.dbUpgraded = False
        self.forceTickle = True
        self._ircs = ircutils.IrcDict()
        self.getIrc(irc)
        self.smartLog = ircutils.IrcDict()
        self.recaps = re.compile("[A-Z]")
        self.starting = world.starting
        if self.registryValue('announceNagInterval') > 0:
            schedule.addEvent(self.checkNag, time.time() +
                self.registryValue('announceNagInterval'), 'ChanTracker')

    def checkNag(self):
        if world:
            if world.ircs:
                for irc in world.ircs:
                    for channel in list(irc.state.channels.keys()):
                        if not self.registryValue('enabled', channel=channel, network=irc.network):
                            continue
                        logChannel = self.registryValue('logChannel', channel=channel, network=irc.network)
                        if logChannel and logChannel in irc.state.channels:
                            toNag = ''
                            for mode in self.registryValue('announceNagMode', channel=channel, network=irc.network):
                                if len(mode) and mode in irc.state.channels[channel].modes:
                                    toNag = mode
                                    break
                            if len(toNag):
                                if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                                    self._logChan(irc, channel, '[%s] has %s mode' % (
                                        ircutils.bold(channel), ircutils.bold(ircutils.mircColor(toNag, 'red'))))
                                else:
                                    self._logChan(irc, channel, '[%s] has %s mode' % (channel, toNag))
        if self.registryValue('announceNagInterval') > 0:
            schedule.addEvent(self.checkNag, time.time() +
                self.registryValue('announceNagInterval'), 'ChanTracker')

    def weblink(self, irc, msg, args, user):
        """takes no arguments

        provides link to web interface"""
        allowed = False
        for capab in user.capabilities:
            if capab in ('owner', 'admin') or capab.endswith(',op'):
                allowed = True
                break
        if allowed:
            irc.reply(server.weblink(), private=True)
        else:
            irc.errorNoCapability('#channel,op')
        self.forceTickle = True
        self._tickle(irc)
    weblink = wrap(weblink, ['user'])

    def summary(self, irc, msg, args, channel):
        """[<channel>]

        returns various statistics about channel activity"""
        c = self.getChan(irc, channel)
        messages = c.summary(self.getDb(irc.network))
        irc.replies(messages, onlyPrefixFirst=True, private=True)
        self.forceTickle = True
        self._tickle(irc)
    summary = wrap(summary, ['op', 'channel'])

    def extract(self, irc, msg, args, channel, newChannel):
        """[<channel>] [<newChannel>]

        returns a snapshot of ChanTracker settings for the given <channel>;
        if <newChannel> is provided, settings are copied"""
        namespace = 'supybot.plugins.ChanTracker'
        group = getWrapper(namespace)
        L = listGroup(group)
        msgs = []
        props = []
        for prop in L:
            p = getWrapper('%s.%s' % (namespace, prop))
            if p.channelValue:
                value = str(p) or ''
                channelValue = str(p.get(channel))
                if value != channelValue:
                    props.append([prop, channelValue])
                    msgs.append(ircmsgs.privmsg(msg.nick, 'config channel %s %s.%s %s' % (
                        channel, namespace, prop, channelValue)))
        if len(msgs):
            if newChannel:
                for prop in props:
                    newChan = getWrapper('%s.%s.%s' % (namespace, prop[0], newChannel))
                    newChan.set(prop[1])
                irc.replySuccess()
            else:
                for m in msgs:
                    irc.queueMsg(m)
        else:
            irc.reply("%s uses global's settings" % channel)
        self.forceTickle = True
        self._tickle(irc)
    extract = wrap(extract, ['owner', 'private', 'channel', optional('validChannel')])

    def editandmark(self, irc, msg, args, user, ids, seconds, reason):
        """<id>[,<id>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<reason>]

        change expiry and mark of an active mode change; if you got this message
        while the bot prompted you, your changes were not saved;
        <-1s> means forever, <0s> means remove"""
        i = self.getIrc(irc)
        b = False
        lc = self._logChan
        duration = getDuration(seconds)
        for uid in ids:
            be = False
            bm = False
            item = i.getItem(irc, uid)
            if item:
                f = None
                suppZero = duration == 0 \
                    and not self.registryValue('announceInTimeEditAndMark',
                    channel=item.channel, network=irc.network)
                if not suppZero and reason and self.registryValue(
                        'useSmartLog', channel=item.channel, network=irc.network):
                    key = '%s|%s' % (item.mode, item.value)
                    self.smartLog[key] = []
                if self.registryValue('announceEdit', channel=item.channel, network=irc.network) \
                        and not suppZero:
                    f = self._logChan
                be = i.edit(irc, item.channel, item.mode, item.value, duration,
                    msg.prefix, self.getDb(irc.network), self._schedule, f, self)
                if be and reason:
                    if self.registryValue('announceMark', channel=item.channel, network=irc.network):
                        f = self._logChan
                    bm = i.mark(irc, uid, reason, msg.prefix, self.getDb(irc.network), f, self)
                b = be and bm
            if not b:
                break
        if b:
            irc.replySuccess()
            self.hasAskedItems(irc, msg.prefix, remove=True, prompt=False)
            found = self.hasAskedItems(irc, msg.prefix, remove=False, prompt=True)
            if found:
                i.askedItems[msg.prefix][found[0]][6] = True
                i.lowQueue.enqueue(ircmsgs.privmsg(msg.nick, found[5]))
        else:
            irc.reply('item not found, already removed or not enough rights to modify it')
        self.forceTickle = True
        self._tickle(irc)
    editandmark = wrap(editandmark, ['user', commalist('int'), many('getTs', True), rest('text')])

    def edit(self, irc, msg, args, user, ids, seconds):
        """<id>[,<id>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s]

        change expiry of an active mode change; <-1s> means forever, <0s> means remove"""
        i = self.getIrc(irc)
        b = False
        sf = None
        duration = getDuration(seconds)
        if not len(ids) > 1:
            sf = self._schedule
        for uid in ids:
            item = i.getItem(irc, uid)
            if item:
                f = None
                if not (duration == 0
                        and not self.registryValue('announceInTimeEditAndMark',
                        channel=item.channel, network=irc.network)) \
                        and ((msg.prefix != irc.prefix and self.registryValue(
                        'announceEdit', channel=item.channel, network=irc.network))
                        or (msg.prefix == irc.prefix and self.registryValue(
                        'announceBotEdit', channel=item.channel, network=irc.network))):
                    f = self._logChan
                b = i.edit(irc, item.channel, item.mode, item.value, duration,
                    msg.prefix, self.getDb(irc.network), sf, f, self)
            if not b:
                break
        if not sf and duration > 0:
            self._schedule(irc, time.time()+duration, True)
        if not msg.nick == irc.nick:
            if b:
                irc.replySuccess()
            else:
                irc.reply('item not found, already removed or not enough rights to modify it')
        self.forceTickle = True
        self._tickle(irc)
    edit = wrap(edit, ['user', commalist('int'), many('getTs')])

    def info(self, irc, msg, args, user, uid):
        """<id>

        summary of a mode change"""
        i = self.getIrc(irc)
        results = i.info(irc, uid, msg.prefix, self.getDb(irc.network))
        if len(results):
            msgs = []
            for message in results:
                msgs.append(message[1])
            if self.registryValue('allowPublicInfo', channel=results[0][0], network=irc.network):
                irc.replies(msgs, None, None, True, None)
            else:
                irc.replies(msgs, onlyPrefixFirst=True, private=True)
        else:
            irc.reply('item not found or not enough rights to see information')
        self.forceTickle = True
        self._tickle(irc)
    info = wrap(info, ['user', 'int'])

    def detail(self, irc, msg, args, user, uid):
        """<id>

        logs of a mode change"""
        i = self.getIrc(irc)
        results = i.log(irc, uid, msg.prefix, self.getDb(irc.network))
        if len(results):
            irc.replies(results, None, None, False)
        else:
            irc.reply('item not found or not enough rights to see detail')
        self.forceTickle = True
        self._tickle(irc)
    detail = wrap(detail, ['user', 'int'])

    def affect(self, irc, msg, args, user, uid):
        """<id>

        list users affected by a mode change"""
        i = self.getIrc(irc)
        results = i.affect(irc, uid, msg.prefix, self.getDb(irc.network))
        if len(results):
            irc.replies(results, None, None, False)
        else:
            irc.reply('item not found or not enough rights to see affected users')
        self.forceTickle = True
        self._tickle(irc)
    affect = wrap(affect, ['user', 'int'])

    def mark(self, irc, msg, args, user, ids, message):
        """<id>[,<id>] <message>

        add comment on a mode change"""
        i = self.getIrc(irc)
        b = False
        for uid in ids:
            item = i.getItem(irc, uid)
            if item:
                f = None
                if (msg.prefix != irc.prefix and self.registryValue(
                        'announceMark', channel=item.channel, network=irc.network)) \
                        or (msg.prefix == irc.prefix and self.registryValue(
                        'announceBotMark', channel=item.channel, network=irc.network)):
                    f = self._logChan
                b = i.mark(irc, uid, message, msg.prefix, self.getDb(irc.network), f, self)
            else:
                b = i.markremoved(irc, uid, message, msg.prefix, self.getDb(irc.network), self)
            if not b:
                break
        if not msg.nick == irc.nick:
            if b:
                irc.replySuccess()
            else:
                irc.reply('item not found or not enough rights to mark it')
        self.forceTickle = True
        self._tickle(irc)
    mark = wrap(mark, ['user', commalist('int'), 'text'])

    def query(self, irc, msg, args, user, optlist, text):
        """[--deep] [--never] [--active] [--ids] [--channel=<channel>] <pattern|hostmask|comment>

        search in tracking database; --deep to search in logs, --never returns items set forever and active,
        --active returns only active modes, --ids returns only ids, --channel limits results to the specified channel"""
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
        results = i.search(irc, text, msg.prefix, self.getDb(irc.network), deep, active, never, channel, ids)
        if len(results):
            irc.replies(results, None, None, False)
        else:
            irc.reply('nothing found')
    query = wrap(query, ['user', getopts({'deep': '', 'never': '', 'ids': '', 'active': '', 'channel': 'channel'}), 'text'])

    def pending(self, irc, msg, args, channel, optlist):
        """[<channel>] [--mode=<e|b|q|l>] [--oper=<nick|hostmask>] [--never] [--ids] [--count] [--flood] [--duration [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s]]

        returns active items for --mode, filtered by --oper, --never (never expire), --ids (only ids),
        --duration (item longer than), --count returns the total, --flood one message per mode"""
        mode = None
        oper = None
        never = False
        ids = False
        count = False
        flood = False
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
            elif option == 'count':
                count = True
            elif option == 'flood':
                flood = True
        if never and duration > 0:
            irc.reply("you can't use --never and --duration at the same time")
            return
        i = self.getIrc(irc)
        if oper in i.nicks:
            oper = self.getNick(irc, oper).prefix
        results = []
        if not mode:
            mode = self.registryValue('modesToAskWhenOpped', channel=channel, network=irc.network) \
                + self.registryValue('modesToAsk', channel=channel, network=irc.network)
        results = i.pending(irc, channel, mode, msg.prefix, oper,
            self.getDb(irc.network), never, ids, duration)
        if len(results):
            if count:
                irc.reply('%s items' % len(results), private=True)
            else:
                if not flood:
                    irc.reply(', '.join(results), private=True)
                else:
                    irc.replies(results, onlyPrefixFirst=True, private=True)
        else:
            irc.reply('nothing found')
        self.forceTickle = True
        self._tickle(irc)
    pending = wrap(pending, ['op', getopts({'flood': '', 'mode': 'letter', 'never': '',
        'oper': 'somethingWithoutSpaces', 'ids': '', 'count': '', 'duration': 'getTs'})])

    def _modes(self, numModes, chan, modes, f):
        for i in range(0, len(modes), numModes):
            chan.action.enqueue(f(modes[i:i + numModes]))

    def modes(self, irc, msg, args, channel, delay, modes):
        """[<channel>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] <mode> [<arg> ...]

        sets the mode in <channel> to <mode>, sending the arguments given;
        <channel> is only necessary if the message isn't sent in the channel
        itself, <delay> is optional"""
        def f(L):
            return ircmsgs.modes(channel, L)
        def la():
            self._modes(irc.state.supported.get('modes', 1), self.getChan(irc, channel),
                ircutils.separateModes(modes), f)
            self.forceTickle = True
            self._tickle(irc)
        duration = getDuration(delay)
        if duration is not None and duration > 0:
            schedule.addEvent(la, time.time()+duration)
        else:
            la()
        irc.replySuccess()
        self.forceTickle = True
        self._tickle(irc)
    modes = wrap(modes, ['op', any('getTs', True), many('something')])

    def do(self, irc, msg, args, channel, mode, items, seconds, reason):
        """[<channel>] <mode> <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] <reason>

        +<mode> targets for duration; <reason> is mandatory, <-1s> means forever, empty means default"""
        if mode in self.registryValue('modesToAsk', channel=channel, network=irc.network) \
                or mode in self.registryValue('modesToAskWhenOpped', channel=channel, network=irc.network):
            b = self._adds(irc, msg, args, channel, mode, items, getDuration(seconds), reason, False)
            if msg.nick != irc.nick and not b:
                irc.reply('nicks not found or hostmasks invalid or targets are already +%s' % mode)
        else:
            irc.reply('selected mode is not supported by config, see modesToAsk and modesToAskWhenOpped')
        self.forceTickle = True
        self._tickle(irc)
    do = wrap(do, ['op', 'letter', commalist('something'), any('getTs', True), rest('text')])

    def q(self, irc, msg, args, channel, items, seconds, reason):
        """[<channel>] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] <reason>

        +q targets for duration; <reason> is mandatory, <-1s> means forever, empty means default"""
        b = self._adds(irc, msg, args, channel, 'q', items, getDuration(seconds), reason, False)
        if msg.nick != irc.nick and not b:
            irc.reply('nicks not found or hostmasks invalid or targets are already +q')
        self.forceTickle = True
        self._tickle(irc)
    q = wrap(q, ['op', commalist('something'), any('getTs', True), rest('text')])

    def b(self, irc, msg, args, channel, optlist, items, seconds, reason):
        """[<channel>] [--perm] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] <reason>

        +b targets for duration; <reason> is mandatory, <-1s> means forever, empty means default,
        add --perm if you want to add it to permanent bans of channel"""
        perm = False
        for (option, arg) in optlist:
            if option == 'perm':
                perm = True
        b = self._adds(irc, msg, args, channel, 'b', items, getDuration(seconds), reason, perm)
        if msg.nick != irc.nick and not b:
            irc.reply('nicks not found or hostmasks invalid or targets are already +b')
        self.forceTickle = True
        self._tickle(irc)
    b = wrap(b, ['op', getopts({'perm': ''}), commalist('something'), any('getTs', True), rest('text')])

    def i(self, irc, msg, args, channel, items, seconds, reason):
        """[<channel>] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] <reason>

        +I targets for duration; <reason> is mandatory, <-1s> means forever, empty means default"""
        b = self._adds(irc, msg, args, channel, 'I', items, getDuration(seconds), reason, False)
        if msg.nick != irc.nick and not b:
            irc.reply('nicks not found or hostmasks invalid or targets are already +I')
        self.forceTickle = True
        self._tickle(irc)
    i = wrap(i, ['op', commalist('something'), any('getTs', True), rest('text')])

    def e(self, irc, msg, args, channel, items, seconds, reason):
        """[<channel>] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] <reason>

        +e targets for duration; <reason> is mandatory, <-1s> means forever, empty means default"""
        b = self._adds(irc, msg, args, channel, 'e', items, getDuration(seconds), reason, False)
        if msg.nick != irc.nick and not b:
            irc.reply('nicks not found or hostmasks invalid or targets are already +e')
        self.forceTickle = True
        self._tickle(irc)
    e = wrap(e, ['op', commalist('something'), any('getTs', True), rest('text')])

    def undo(self, irc, msg, args, channel, mode, items):
        """[<channel>] <mode> <nick|hostmask|*> [<nick|hostmask|*>]

        sets -<mode> on them; if * is given, remove them all"""
        b = self._removes(irc, msg, args, channel, mode, items, False)
        if msg.nick != irc.nick and not b:
            irc.reply('nicks not found or hostmasks invalid or targets are not +%s' % mode)
        self.forceTickle = True
        self._tickle(irc)
    undo = wrap(undo, ['op', 'letter', many('something')])

    def uq(self, irc, msg, args, channel, items):
        """[<channel>] <nick|hostmask|*> [<nick|hostmask|*>]

        sets -q on them; if * is given, remove them all"""
        isMass = False
        for item in items:
            if item == '*':
                isMass = True
        if isMass and not self.registryValue('removeAllQuiets', channel=channel, network=irc.network):
            irc.reply('removal of all quiets has been disabled for %s' % channel)
            return
        b = self._removes(irc, msg, args, channel, 'q', items, False)
        if msg.nick != irc.nick and not b:
            irc.reply('nicks not found or hostmasks invalid or targets are not +q')
        self.forceTickle = True
        self._tickle(irc)
    uq = wrap(uq, ['op', many('something')])

    def ub(self, irc, msg, args, channel, optlist, items):
        """[<channel>] [--perm] <nick|hostmask|*> [<nick|hostmask|*>]

        sets -b on them; if * is given, remove them all,
        --perm to remove them for permanent bans"""
        perm = False
        for (option, arg) in optlist:
            if option == 'perm':
                perm = True
        isMass = False
        for item in items:
            if item == '*':
                isMass = True
        if isMass and not self.registryValue('removeAllBans', channel=channel, network=irc.network):
            irc.reply('removal of all bans has been disabled for %s' % channel)
            return
        b = self._removes(irc, msg, args, channel, 'b', items, perm)
        if msg.nick != irc.nick and not b:
            if perm:
                if len(items) == 1:
                    irc.reply('nicks not found or hostmasks invalid or targets are not +b; '
                        + 'you may try "channel ban remove %s %s"' % (channel, items[0]))
                else:
                    irc.reply('nicks not found or hostmasks invalid or targets are not +b; '
                        + 'you may try "channel ban remove %s %s"' % (channel, ''))
            else:
                irc.reply('nicks not found or hostmasks invalid or targets are not +b')
        self.forceTickle = True
        self._tickle(irc)
    ub = wrap(ub, ['op', getopts({'perm': ''}), many('something')])

    def ui(self, irc, msg, args, channel, items):
        """[<channel>] <nick|hostmask|*> [<nick|hostmask|*>]

        sets -I on them; if * is given, remove them all"""
        isMass = False
        for item in items:
            if item == '*':
                isMass = True
        if isMass and not self.registryValue('removeAllInvites', channel=channel, network=irc.network):
            irc.reply('removal of all invites has been disabled for %s' % channel)
            return
        b = self._removes(irc, msg, args, channel, 'I', items, False)
        if msg.nick != irc.nick and not b:
            irc.reply('nicks not found or hostmasks invalid or targets are not +I')
        self.forceTickle = True
        self._tickle(irc)
    ui = wrap(ui, ['op', many('something')])

    def ue(self, irc, msg, args, channel, items):
        """[<channel>] <nick|hostmask|*> [<nick|hostmask|*>]

        sets -e on them; if * is given, remove them all"""
        isMass = False
        for item in items:
            if item == '*':
                isMass = True
        if isMass and not self.registryValue('removeAllExempts', channel=channel, network=irc.network):
            irc.reply('removal of all exempts has been disabled for %s' % channel)
            return
        b = self._removes(irc, msg, args, channel, 'e', items, False)
        if msg.nick != irc.nick and not b:
            irc.reply('nicks not found or hostmasks invalid or targets are not +e')
        self.forceTickle = True
        self._tickle(irc)
    ue = wrap(ue, ['op', many('something')])

    def r(self, irc, msg, args, channel, nick, reason):
        """[<channel>] <nick> [<reason>]

        force a part on <nick> with <reason> if provided"""
        chan = self.getChan(irc, channel)
        if not reason:
            reason = ''
        if self.registryValue('discloseOperator', channel=channel, network=irc.network):
            if len(reason):
                reason += ' (by %s)' % msg.nick
            else:
                reason = 'by %s' % msg.nick
        chan.action.enqueue(ircmsgs.IrcMsg('REMOVE %s %s :%s' % (channel, nick, reason)))
        self.forceTickle = True
        self._tickle(irc)
    r = wrap(r, ['op', 'nickInChannel', additional('text')])

    def k(self, irc, msg, args, channel, nick, reason):
        """[<channel>] <nick> [<reason>]

        kick <nick> with <reason> if provided"""
        chan = self.getChan(irc, channel)
        if not reason:
            reason = ''
        if self.registryValue('discloseOperator', channel=channel, network=irc.network):
            if len(reason):
                reason += ' (by %s)' % msg.nick
            else:
                reason = 'by %s' % msg.nick
        chan.action.enqueue(ircmsgs.kick(channel, nick, reason))
        self.forceTickle = True
        self._tickle(irc)
    k = wrap(k, ['op', 'nickInChannel', additional('text')])

    def overlap(self, irc, msg, args, channel, mode):
        """[<channel>] <mode>

        returns overlapping modes; there is limitation with extended bans"""
        results = []
        if mode in self.registryValue('modesToAsk', channel=channel, network=irc.network) \
                or mode in self.registryValue('modesToAskWhenOpped', channel=channel, network=irc.network):
            chan = self.getChan(irc, channel)
            modes = chan.getItemsFor(self.getIrcdMode(irc, mode, '*!*@*')[0])
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
                                if match(item.value, n, irc, self.registryValue('resolveIp')):
                                    results.append('[#%s %s] matches [#%s %s]' % (
                                        item.uid, item.value, i.uid, i.value))
                        item = L.pop()
        if len(results):
            irc.reply(' '.join(results), private=True)
        else:
            irc.reply('nothing found or unknown mode')
        self.forceTickle = True
        self._tickle(irc)
    overlap = wrap(overlap, ['op', 'text'])

    def ops(self, irc, msg, args, channel, text):
        """[<reason>]

        triggers ops in the operators channel"""
        if not self.registryValue('triggerOps', channel=channel, network=irc.network):
            return
        if not text:
            text = ''
        if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
            self._logChan(irc, channel, "[%s] %s wants attention from ops (%s)" % (
                ircutils.bold(channel), msg.prefix, text))
        else:
            self._logChan(irc, channel, "[%s] %s wants attention from ops (%s)" % (
                channel, msg.prefix, text))
        self.forceTickle = True
        self._tickle(irc)
    ops = wrap(ops, ['channel', optional('text')])

    def match(self, irc, msg, args, channel, prefix):
        """[<channel>] <nick|hostmask#username>

        returns active modes that affect the given target;
        nick must be in a channel shared with the bot"""
        i = self.getIrc(irc)
        n = None
        if prefix in i.nicks:
            n = self.getNick(irc, prefix)
        else:
            if ircutils.isUserHostmask(prefix):
                n = Nick(0)
                if '#' in prefix:
                    a = prefix.split('#')
                    username = a[1]
                    prefix = a[0]
                    n.setPrefix(prefix)
                    if self.registryValue('resolveIp') and utils.net.isIP(prefix.split('@')[1].split('#')[0]):
                        n.setIp(prefix.split('@')[1].split('#')[0])
                    n.setRealname(username)
                else:
                    n.setPrefix(prefix)
                    if self.registryValue('resolveIp') and utils.net.isIP(prefix.split('@')[1]):
                        n.setIp(prefix.split('@')[1])
            else:
                irc.reply('unknown nick')
                return
        results = i.against(irc, channel, n, msg.prefix, self.getDb(irc.network), self)
        if len(results):
            irc.reply(' '.join(results), private=True)
        else:
            irc.reply('nothing found')
        self._tickle(irc)
    match = wrap(match, ['op', 'text'])

    def check(self, irc, msg, args, channel, pattern):
        """[<channel>] <pattern>

        returns a list of users affected by a pattern"""
        if ircutils.isUserHostmask(pattern) or self.getIrcdExtbansPrefix(irc) in pattern:
            results = []
            i = self.getIrc(irc)
            for nick in list(irc.state.channels[channel].users):
                n = self.getNick(irc, nick)
                m = match(pattern, n, irc, self.registryValue('resolveIp'))
                if m:
                    results.append('[%s - %s]' % (nick, m))
            if len(results):
                irc.reply('%s user(s): %s' % (len(results), ' '.join(results)))
            else:
                irc.reply('nobody will be affected')
        else:
            irc.reply('invalid pattern given')
        self._tickle(irc)
    check = wrap(check, ['op', 'text'])

    def cpmode(self, irc, msg, args, channel, sourceMode, target, targetMode, seconds, reason):
        """[<channelSource>] <channelMode> <channelTarget> <targetMode> [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] <reason>

        copy <channelSource> <channelMode> elements in <channelTarget> on <targetMode>; <-1s> means forever, empty means default"""
        op = ircdb.makeChannelCapability(target, 'op')
        if not ircdb.checkCapability(msg.prefix, op):
            irc.errorNoCapability(op)
            return
        chan = self.getChan(irc, channel)
        targets = set([])
        L = chan.getItemsFor(self.getIrcdMode(irc, sourceMode, '*!*@*')[0])
        for element in L:
            targets.add(L[element].value)
        self._adds(irc, msg, args, target, targetMode, targets, getDuration(seconds), reason, False)
        irc.replySuccess()
        self._tickle(irc)
    cpmode = wrap(cpmode, ['op', 'letter', 'validChannel', 'letter', any('getTs', True), rest('text')])

    def getmask(self, irc, msg, args, channel, prefix):
        """[<channel>] <nick|hostmask>

        returns a list of hostmask patterns, best first; mostly used for debugging"""
        i = self.getIrc(irc)
        if prefix in i.nicks:
            irc.reply(' '.join(getBestPattern(self.getNick(irc, prefix), irc, self.registryValue(
                'useIpForGateway', channel=channel, network=irc.network), self.registryValue('resolveIp'))))
        else:
            n = Nick(0)
            # gecos ($x)
            if '#' in prefix:
                a = prefix.split('#')
                username = a[1]
                prefix = a[0]
                n.setPrefix(prefix)
                n.setRealname(username)
            else:
                n.setPrefix(prefix)
            if ircutils.isUserHostmask(prefix):
                irc.reply(' '.join(getBestPattern(n, irc, self.registryValue(
                    'useIpForGateway', channel=channel, network=irc.network), self.registryValue('resolveIp'))))
                return
            irc.reply('nick not found or wrong hostmask given')
        self._tickle(irc)
    getmask = wrap(getmask, ['op', 'text'])

    def isvip(self, irc, msg, args, channel, nick):
        """[<channel>] <nick>

        tell if <nick> is vip in <channel>; mostly used for debugging"""
        i = self.getIrc(irc)
        if nick in i.nicks:
            vip = self._isVip(irc, channel, self.getNick(irc, nick))
            if not vip:
                vip = 'no vip'
            irc.reply('%s is %s' % (nick, vip))
        else:
            irc.reply('nick not found')
        self._tickle(irc)
    isvip = wrap(isvip, ['op', 'nick'])

    def isbad(self, irc, msg, args, channel, nick):
        """[<channel>] <nick>

        tell if <nick> is flagged as bad in <channel>; mostly used for debugging"""
        i = self.getIrc(irc)
        if nick in i.nicks:
            chan = self.getChan(irc, channel)
            n = self.getNick(irc, nick)
            bests = getBestPattern(n, irc, self.registryValue(
                'useIpForGateway', channel=channel, network=irc.network), self.registryValue('resolveIp'))
            best = bests[0]
            if self.registryValue('useAccountBanIfPossible', channel=channel, network=irc.network) and n.account:
                for p in bests:
                    if p.startswith('$a:'):
                        best = p
                        break
            isWrong = chan.isWrong(best)
            irc.reply(str(isWrong))
        else:
            irc.reply('nick not found')
        self._tickle(irc)
    isbad = wrap(isbad, ['op', 'nick'])

    def vacuum(self, irc, msg, args):
        """VACUUM the database"""
        db = self.getDb(irc.network)
        c = db.cursor()
        c.execute('VACUUM')
        c.close()
        irc.replySuccess()
    vacuum = wrap(vacuum, ['owner'])

    def m(self, irc, msg, args, channel, items, reason):
        """[<channel>] <nick|hostmask>[,<nick|hostmask>] <reason>

        store a new item in database under the mode 'm'; markable but not editable"""
        i = self.getIrc(irc)
        targets = []
        chan = self.getChan(irc, channel)
        for item in items:
            if item in chan.nicks or item in irc.state.channels[channel].users:
                n = self.getNick(irc, item)
                patterns = getBestPattern(n, irc, self.registryValue(
                    'useIpForGateway', channel=channel, network=irc.network), self.registryValue('resolveIp'))
                if len(patterns):
                    pattern = patterns[0]
                    if self.registryValue('useAccountBanIfPossible', channel=channel, network=irc.network) and n.account:
                        for p in patterns:
                            if p.startswith('$a:'):
                                pattern = p
                                break
                    targets.append(pattern)
            elif ircutils.isUserHostmask(item) or self.getIrcdExtbansPrefix(irc) in item:
                targets.append(item)
        for target in targets:
            item = chan.addItem('m', target, msg.prefix, time.time(), self.getDb(irc.network),
                self.registryValue('doActionAgainstAffected', channel=channel, network=irc.network), self)
            f = None
            if msg.prefix != irc.prefix and self.registryValue('announceMark', channel=channel, network=irc.network):
                f = self._logChan
            db = self.getDb(irc.network)
            c = db.cursor()
            c.execute("""UPDATE bans SET removed_at=?, removed_by=? WHERE id=?""",
                (time.time()+1, msg.prefix, int(item.uid)))
            db.commit()
            c.close()
            i.mark(irc, item.uid, reason, msg.prefix, self.getDb(irc.network), f, self)
        if not msg.nick == irc.nick:
            if len(targets):
                irc.replySuccess()
            else:
                irc.reply('unknown patterns')
        self.forceTickle = True
        self._tickle(irc)
    m = wrap(m, ['op', commalist('something'), rest('text')])

    def addpattern(self, irc, msg, args, channel, limit, life, mode, seconds, pattern):
        """[<channel>] <limit> <life> <mode>(bqeIkrd) [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] <pattern>

        add a <pattern> which triggers <mode> for <duration> if the <pattern> appears
        more often than <limit> (0 for immediate action) during <life> in seconds"""
        chan = self.getChan(irc, channel)
        duration = getDuration(seconds)
        if duration is None:
            duration = self.registryValue('autoExpire', channel=channel, network=irc.network)
        result = chan.addpattern(msg.prefix, limit, life, mode, duration,
            pattern, 0, self.getDb(irc.network))
        irc.reply(result)
    addpattern = wrap(addpattern, ['op', 'nonNegativeInt', 'positiveInt', 'letter',
        any('getTs', True), rest('text')])

    def addregexpattern(self, irc, msg, args, channel, limit, life, mode, seconds, pattern):
        """[<channel>] <limit> <life> <mode>(bqeIkrd) [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] /<pattern>/

        add a <pattern> which triggers <mode> for <duration> if the <pattern> appears
        more often than <limit> (0 for immediate action) during <life> in seconds"""
        chan = self.getChan(irc, channel)
        duration = getDuration(seconds)
        if duration is None:
            duration = self.registryValue('autoExpire', channel=channel, network=irc.network)
        result = chan.addpattern(msg.prefix, limit, life, mode, duration,
            pattern[0], 1, self.getDb(irc.network))
        irc.reply(result)
        self.forceTickle = True
        self._tickle(irc)
    addregexpattern = wrap(addregexpattern, ['op', 'nonNegativeInt', 'positiveInt', 'letter',
        any('getTs', True), rest('getPatternAndMatcher')])

    def rmpattern(self, irc, msg, args, channel, ids):
        """[<channel>] <id>[,<id>]

        remove patterns by <id>"""
        results = []
        chan = self.getChan(irc, channel)
        for uid in ids:
            result = chan.rmpattern(msg.prefix, uid, self.getDb(irc.network))
            if result:
                results.append(result)
        if len(results):
            irc.reply('%s removed: %s' % (len(results), ','.join(results)))
        else:
            irc.reply('nothing found')
        self.forceTickle = True
        self._tickle(irc)
    rmpattern = wrap(rmpattern, ['op', commalist('int')])

    def lspattern(self, irc, msg, args, channel, pattern):
        """[<channel>] [<id|pattern>]

        return patterns in <channel> filtered by optional <id> or <pattern>"""
        results = []
        chan = self.getChan(irc, channel)
        results = chan.lspattern(msg.prefix, pattern, self.getDb(irc.network))
        if len(results):
            irc.replies(results, None, None, False)
        else:
            irc.reply('nothing found')
        self._tickle(irc)
    lspattern = wrap(lspattern, ['op', optional('text')])

    def rmmode(self, irc, msg, args, ids):
        """<id>[,<id>]

        remove entries from database, bot owner command only"""
        i = self.getIrc(irc)
        results = []
        for uid in ids:
            b = i.remove(uid, self.getDb(irc.network))
            if b:
                results.append(str(uid))
        irc.reply('%s' % ', '.join(results))
        self._tickle(irc)
    rmmode = wrap(rmmode, ['owner', commalist('int')])

    def rmtmp(self, irc, msg, args, channel):
        """[<channel>]

        remove temporary patterns if any"""
        chan = self.getChan(irc, channel)
        key = 'pattern%s' % channel
        if key in chan.repeatLogs:
            life = self.registryValue('repeatPatternLife', channel=channel, network=irc.network)
            chan.repeatLogs[key] = utils.structures.TimeoutQueue(life)
        irc.replySuccess()
        self.forceTickle = True
        self._tickle(irc)
    rmtmp = wrap(rmtmp, ['op'])

    def addtmp(self, irc, msg, args, channel, pattern):
        """[<channel>] <pattern>

        add temporary pattern, which follows repeat punishments"""
        self._addTemporaryPattern(irc, channel, pattern, msg.nick, True, False)
        irc.replySuccess()
        self.forceTickle = True
        self._tickle(irc)
    addtmp = wrap(addtmp, ['op', 'text'])

    def cautoexpire(self, irc, msg, args, channel, autoexpire):
        """[<channel>] [<autoexpire>]

        return channel's config or auto remove new elements after <autoexpire> (-1 to disable, in seconds)"""
        cap = ircdb.canonicalCapability('owner')
        if self.registryValue('allowOpToConfig', channel=channel, network=irc.network) \
                or ircdb.checkCapability(msg.prefix, cap):
            results = ['for %s' % channel]
            if autoexpire is not None:
                self.setRegistryValue('autoExpire', autoexpire, channel=channel, network=irc.network)
            results.append('autoExpire: %s' % self.registryValue('autoExpire', channel=channel, network=irc.network))
            irc.replies(results, None, None, False)
            return
        irc.reply("Operators aren't allowed to see or change protection configuration in %s" % channel)
    cautoexpire = wrap(cautoexpire, ['op', optional('int')])

    def cflood(self, irc, msg, args, channel, permit, life, mode, duration):
        """[<channel>] [<permit>] [<life>] [<mode>] [<duration>]

        return channel's config or apply <mode> (bqeIkrdD) for <duration> (in seconds)
        if a user sends more than <permit> (-1 to disable) messages during <life> (in seconds)"""
        cap = ircdb.canonicalCapability('owner')
        if self.registryValue('allowOpToConfig', channel=channel, network=irc.network) \
                or ircdb.checkCapability(msg.prefix, cap):
            results = ['for %s' % channel]
            if not (permit is None or life is None or mode is None or duration is None):
                self.setRegistryValue('floodPermit', permit, channel=channel, network=irc.network)
                self.setRegistryValue('floodLife', life, channel=channel, network=irc.network)
                self.setRegistryValue('floodMode', mode, channel=channel, network=irc.network)
                self.setRegistryValue('floodDuration', duration, channel=channel, network=irc.network)
            results.append('floodPermit: %s' % self.registryValue('floodPermit', channel=channel, network=irc.network))
            results.append('floodLife: %s' % self.registryValue('floodLife', channel=channel, network=irc.network))
            results.append('floodMode: %s' % self.registryValue('floodMode', channel=channel, network=irc.network))
            results.append('floodDuration: %s' % self.registryValue('floodDuration', channel=channel, network=irc.network))
            irc.replies(results, None, None, False)
            return
        irc.reply("Operators aren't allowed to see or change protection configuration in %s" % channel)
    cflood = wrap(cflood, ['op', optional('int'), optional('positiveInt'),
        optional('letter'), optional('positiveInt')])

    def crepeat(self, irc, msg, args, channel, permit, life, mode, duration, minimum, probability, count, patternLength, patternLife):
        """[<channel>] [<permit>] [<life>] [<mode>] [<duration>] [<minimum>] [<probability>] [<count>] [<patternLength>] [<patternLife>]

        return channel's config or apply <mode> (bqeIkrdD) for <duration> (in seconds)
        if <permit> (-1 to disable) repetitions are found during <life> (in seconds);
        it will create a temporary lethal pattern with a mininum of <patternLength>
        (-1 to disable pattern creation); <probablity> is a float between 0 and 1"""
        cap = ircdb.canonicalCapability('owner')
        if self.registryValue('allowOpToConfig', channel=channel, network=irc.network) \
                or ircdb.checkCapability(msg.prefix, cap):
            results = ['for %s' % channel]
            if not (permit is None or life is None or mode is None or duration is None
                    or minimum is None or probability is None or count is None
                    or patternLength is None or patternLife is None):
                self.setRegistryValue('repeatPermit', permit, channel=channel, network=irc.network)
                self.setRegistryValue('repeatLife', life, channel=channel, network=irc.network)
                self.setRegistryValue('repeatMode', mode, channel=channel, network=irc.network)
                self.setRegistryValue('repeatDuration', duration, channel=channel, network=irc.network)
                self.setRegistryValue('repeatMinimum', minimum, channel=channel, network=irc.network)
                self.setRegistryValue('repeatPercent', probability, channel=channel, network=irc.network)
                self.setRegistryValue('repeatCount', count, channel=channel, network=irc.network)
                self.setRegistryValue('repeatPatternMinimum', patternLength, channel=channel, network=irc.network)
                self.setRegistryValue('repeatPatternLife', patternLife, channel=channel, network=irc.network)
            results.append('repeatPermit: %s' % self.registryValue('repeatPermit', channel=channel, network=irc.network))
            results.append('repeatLife: %s' % self.registryValue('repeatLife', channel=channel, network=irc.network))
            results.append('repeatMode: %s' % self.registryValue('repeatMode', channel=channel, network=irc.network))
            results.append('repeatDuration: %s' % self.registryValue('repeatDuration', channel=channel, network=irc.network))
            results.append('repeatMinimum: %s' % self.registryValue('repeatMinimum', channel=channel, network=irc.network))
            results.append('repeatPercent: %s' % self.registryValue('repeatPercent', channel=channel, network=irc.network))
            results.append('repeatCount: %s' % self.registryValue('repeatCount', channel=channel, network=irc.network))
            results.append('repeatPatternMinimum: %s' % self.registryValue('repeatPatternMinimum', channel=channel, network=irc.network))
            results.append('repeatPatternLife: %s' % self.registryValue('repeatPatternLife', channel=channel, network=irc.network))
            irc.replies(results, None, None, False)
            return
        irc.reply("Operators aren't allowed to see or change protection configuration in %s" % channel)
    crepeat = wrap(crepeat, ['op', optional('int'), optional('positiveInt'), optional('letter'),
        optional('positiveInt'), optional('int'), optional('proba'), optional('positiveInt'),
        optional('int'), optional('positiveInt')])

    def ccap(self, irc, msg, args, channel, permit, life, mode, duration, probability):
        """[<channel>] [<permit>] [<life>] [<mode>] [<duration>] [<probability>]

        return channel's config or apply <mode> (bqeIkrdD) for <duration> (in seconds)
        if <permit> (-1 to disable) messages during <life> (in seconds)
        contain more than <probability> (float between 0-1) uppercase chars"""
        cap = ircdb.canonicalCapability('owner')
        if self.registryValue('allowOpToConfig', channel=channel, network=irc.network) \
                or ircdb.checkCapability(msg.prefix, cap):
            results = ['for %s' % channel]
            if not (permit is None or life is None or mode is None
                    or duration is None or probability is None):
                self.setRegistryValue('capPermit', permit, channel=channel, network=irc.network)
                self.setRegistryValue('capLife', life, channel=channel, network=irc.network)
                self.setRegistryValue('capMode', mode, channel=channel, network=irc.network)
                self.setRegistryValue('capDuration', duration, channel=channel, network=irc.network)
                self.setRegistryValue('capPercent', probability, channel=channel, network=irc.network)
            results.append('capPermit: %s' % self.registryValue('capPermit', channel=channel, network=irc.network))
            results.append('capLife: %s' % self.registryValue('capLife', channel=channel, network=irc.network))
            results.append('capMode: %s' % self.registryValue('capMode', channel=channel, network=irc.network))
            results.append('capDuration: %s' % self.registryValue('capDuration', channel=channel, network=irc.network))
            results.append('capPercent: %s' % self.registryValue('capPercent', channel=channel, network=irc.network))
            irc.replies(results, None, None, False)
            return
        irc.reply("Operators aren't allowed to see or change protection configuration in %s" % channel)
    ccap = wrap(ccap, ['op', optional('int'), optional('positiveInt'), optional('letter'),
        optional('positiveInt'), optional('proba')])

    def chl(self, irc, msg, args, channel, permit, mode, duration):
        """[<channel>] [<permit>] [<mode>] [<duration>]

        return channel's config or apply <mode> (bqeIkrdD) during <duration> (in seconds)
        if <permit> (-1 to disable) channel nicks are found in a message"""
        cap = ircdb.canonicalCapability('owner')
        if self.registryValue('allowOpToConfig', channel=channel, network=irc.network) \
                or ircdb.checkCapability(msg.prefix, cap):
            results = ['for %s' % channel]
            if not (permit is None or mode is None or duration is None):
                self.setRegistryValue('hilightPermit', permit, channel=channel, network=irc.network)
                self.setRegistryValue('hilightMode', mode, channel=channel, network=irc.network)
                self.setRegistryValue('hilightDuration', duration, channel=channel, network=irc.network)
            results.append('hilightPermit: %s' % self.registryValue('hilightPermit', channel=channel, network=irc.network))
            results.append('hilightMode: %s' % self.registryValue('hilightMode', channel=channel, network=irc.network))
            results.append('hilightDuration: %s' % self.registryValue('hilightDuration', channel=channel, network=irc.network))
            irc.replies(results, None, None, False)
            return
        irc.reply("Operators aren't allowed to see or change protection configuration in %s" % channel)
    chl = wrap(chl, ['op', optional('int'), optional('letter'), optional('positiveInt')])

    def cclone(self, irc, msg, args, channel, permit, mode, duration):
        """[<channel>] [<permit>] [<mode>] [<duration>]

        return channel's config or apply <mode> (bqeIkrdD) for <duration> (in seconds)
        if <permit> (-1 to disable) users with the same host join the channel"""
        cap = ircdb.canonicalCapability('owner')
        if self.registryValue('allowOpToConfig', channel=channel, network=irc.network) \
                or ircdb.checkCapability(msg.prefix, cap):
            results = ['for %s' % channel]
            if not (permit is None or mode is None or duration is None):
                self.setRegistryValue('clonePermit', permit, channel=channel, network=irc.network)
                self.setRegistryValue('cloneMode', mode, channel=channel, network=irc.network)
                self.setRegistryValue('cloneDuration', duration, channel=channel, network=irc.network)
            results.append('clonePermit: %s' % self.registryValue('clonePermit', channel=channel, network=irc.network))
            results.append('cloneMode: %s' % self.registryValue('cloneMode', channel=channel, network=irc.network))
            results.append('cloneDuration: %s' % self.registryValue('cloneDuration', channel=channel, network=irc.network))
            irc.replies(results, None, None, False)
            return
        irc.reply("Operators aren't allowed to see or change protection configuration in %s" % channel)
    cclone = wrap(cclone, ['op', optional('int'), optional('letter'), optional('positiveInt')])

    def cnotice(self, irc, msg, args, channel, permit, life, mode, duration):
        """[<channel>] [<permit>] [<life>] [<mode>] [<duration>]

        return channel's config or apply <mode> (bqeIkrdD) for <duration> (in seconds)
        if <permit> (-1 to disable) messages are channel notices during <life> (in seconds)"""
        cap = ircdb.canonicalCapability('owner')
        if self.registryValue('allowOpToConfig', channel=channel, network=irc.network) \
                or ircdb.checkCapability(msg.prefix, cap):
            results = ['for %s' % channel]
            if not (permit is None or life is None or mode is None or duration is None):
                self.setRegistryValue('noticePermit', permit, channel=channel, network=irc.network)
                self.setRegistryValue('noticeLife', life, channel=channel, network=irc.network)
                self.setRegistryValue('noticeMode', mode, channel=channel, network=irc.network)
                self.setRegistryValue('noticeDuration', duration, channel=channel, network=irc.network)
            results.append('noticePermit: %s' % self.registryValue('noticePermit', channel=channel, network=irc.network))
            results.append('noticeLife: %s' % self.registryValue('noticeLife', channel=channel, network=irc.network))
            results.append('noticeMode: %s' %self.registryValue('noticeMode', channel=channel, network=irc.network))
            results.append('noticeDuration: %s' % self.registryValue('noticeDuration', channel=channel, network=irc.network))
            irc.replies(results, None, None, False)
            return
        irc.reply("Operators aren't allowed to see or change protection configuration in %s" % channel)
    cnotice = wrap(cnotice, ['op', optional('int'), optional('positiveInt'),
        optional('letter'), optional('positiveInt')])

    def ccycle(self, irc, msg, args, channel, permit, life, mode, duration):
        """[<channel>] [<permit>] [<life>] [<mode>] [<duration>]

        return channel's config  or apply <mode> (bqeIkrdD) for <duration> (in seconds)
        if <permit> (-1 to disable) parts/quits are received by a host during <life> (in seconds)"""
        cap = ircdb.canonicalCapability('owner')
        if self.registryValue('allowOpToConfig', channel=channel, network=irc.network) \
                or ircdb.checkCapability(msg.prefix, cap):
            results = ['for %s' % channel]
            if not (permit is None or life is None or mode is None or duration is None):
                self.setRegistryValue('cyclePermit', permit, channel=channel, network=irc.network)
                self.setRegistryValue('cycleLife', life, channel=channel, network=irc.network)
                self.setRegistryValue('cycleMode', mode, channel=channel, network=irc.network)
                self.setRegistryValue('cycleDuration', duration, channel=channel, network=irc.network)
            results.append('cyclePermit: %s' % self.registryValue('cyclePermit', channel=channel, network=irc.network))
            results.append('cycleLife: %s' % self.registryValue('cycleLife', channel=channel, network=irc.network))
            results.append('cycleMode: %s' % self.registryValue('cycleMode', channel=channel, network=irc.network))
            results.append('cycleDuration: %s' % self.registryValue('cycleDuration', channel=channel, network=irc.network))
            irc.replies(results, None, None, False)
            return
        irc.reply("Operators aren't allowed to see or change protection configuration in %s" % channel)
    ccycle = wrap(ccycle, ['op', optional('int'), optional('positiveInt'),
        optional('letter'), optional('positiveInt')])

    def cnick(self, irc, msg, args, channel, permit, life, mode, duration):
        """[<channel>] [<permit>] [<life>] [<mode>] [<duration>]

        return channel's config or apply <mode> (bqeIkrdD) during <duration> (in seconds)
        if a user changes nick <permit> (-1 to disable) times during <life> (in seconds)"""
        cap = ircdb.canonicalCapability('owner')
        if self.registryValue('allowOpToConfig', channel=channel, network=irc.network) \
                or ircdb.checkCapability(msg.prefix, cap):
            results = ['for %s' % channel]
            if not (permit is None or life is None or mode is None or duration is None):
                self.setRegistryValue('nickPermit', permit, channel=channel, network=irc.network)
                self.setRegistryValue('nickLife', life, channel=channel, network=irc.network)
                self.setRegistryValue('nickMode', mode, channel=channel, network=irc.network)
                self.setRegistryValue('nickDuration', duration, channel=channel, network=irc.network)
            results.append('nickPermit: %s' %self.registryValue('nickPermit', channel=channel, network=irc.network))
            results.append('nickLife: %s' % self.registryValue('nickLife', channel=channel, network=irc.network))
            results.append('nickMode: %s' % self.registryValue('nickMode', channel=channel, network=irc.network))
            results.append('nickDuration: %s' % self.registryValue('nickDuration', channel=channel, network=irc.network))
            irc.replies(results, None, None, False)
            return
        irc.reply("Operators aren't allowed to see or change protection configuration in %s" % channel)
    cnick = wrap(cnick, ['op', optional('int'), optional('positiveInt'),
        optional('letter'), optional('positiveInt')])

    def cbad(self, irc, msg, args, channel, permit, life, mode, duration):
        """[<channel>] [<permit>] [<life>] [<mode>] [<duration>]

        return channel's config or apply <mode> (bqeIkrdD) for <duration> (in seconds)
        if a user triggers <permit> (-1 to disable) channel protections during <life> (in seconds)"""
        cap = ircdb.canonicalCapability('owner')
        if self.registryValue('allowOpToConfig', channel=channel, network=irc.network) \
                or ircdb.checkCapability(msg.prefix, cap):
            results = ['for %s' % channel]
            if not (permit is None or life is None or mode is None or duration is None):
                self.setRegistryValue('badPermit', permit, channel=channel, network=irc.network)
                self.setRegistryValue('badLife', life, channel=channel, network=irc.network)
                self.setRegistryValue('badMode', mode, channel=channel, network=irc.network)
                self.setRegistryValue('badDuration', duration, channel=channel, network=irc.network)
            results.append('badPermit: %s' % self.registryValue('badPermit', channel=channel, network=irc.network))
            results.append('badLife: %s' % self.registryValue('badLife', channel=channel, network=irc.network))
            results.append('badMode: %s' % self.registryValue('badMode', channel=channel, network=irc.network))
            results.append('badDuration: %s' % self.registryValue('badDuration', channel=channel, network=irc.network))
            irc.replies(results, None, None, False)
            return
        irc.reply("Operators aren't allowed to see or change protection configuration in %s" % channel)
    cbad = wrap(cbad, ['op', optional('int'), optional('positiveInt'),
        optional('letter'), optional('positiveInt')])

    def getIrcdMode(self, irc, mode, pattern):
        # here we try to know which kind of mode and pattern should be computed:
        # based on supported modes and extbans on the ircd
        # works for q in charybdis, and should work for unreal and inspire
        if 'chanmodes' in irc.state.supported and mode == 'q':
            cm = irc.state.supported['chanmodes'].split(',')[0]
            if mode not in cm:
                if 'extban' in irc.state.supported:
                    extban = irc.state.supported['extban']
                    prefix = extban.split(',')[0]
                    modes = extban.split(',')[1]
                    if mode in modes:
                        # unreal
                        old = mode
                        mode = 'b'
                        if pattern and pattern.find(prefix) != 0:
                            pattern = '%s%s:%s' % (prefix, old, pattern)
                    elif 'm' in modes:
                        # inspire ?
                        mode = 'b'
                        if pattern and not pattern.startswith('m:'):
                            pattern = '%sm:%s' % (prefix, pattern)
        return [mode, pattern]

    def getIrcdExtbansPrefix(self, irc):
        if 'extban' in irc.state.supported:
            return irc.state.supported['extban'].split(',')[0]
        return ''

    def _adds(self, irc, msg, args, channel, mode, items, duration, reason, perm):
        i = self.getIrc(irc)
        targets = []
        if mode in self.registryValue('modesToAsk', channel=channel, network=irc.network) \
                or mode in self.registryValue('modesToAskWhenOpped', channel=channel, network=irc.network):
            chan = self.getChan(irc, channel)
            for item in items:
                if item in chan.nicks or item in irc.state.channels[channel].users:
                    n = self.getNick(irc, item)
                    found = False
                    if self.registryValue('avoidOverlap', channel=channel, network=irc.network):
                        modes = chan.getItemsFor(
                            self.getIrcdMode(irc, mode, n.prefix)[0])
                        if len(modes):
                            for m in modes:
                                md = modes[m]
                                if match(md.value, n, irc, self.registryValue('resolveIp')):
                                    targets.append(md.value)
                                    found = True
                    if not found:
                        patterns = getBestPattern(n, irc, self.registryValue(
                            'useIpForGateway', channel=channel, network=irc.network), self.registryValue('resolveIp'))
                        if len(patterns):
                            pattern = patterns[0]
                            if self.registryValue('useAccountBanIfPossible', channel=channel, network=irc.network) and n.account:
                                for p in patterns:
                                    if p.startswith('$a:'):
                                        pattern = p
                                        break
                            targets.append(pattern)
                elif ircutils.isUserHostmask(item) or self.getIrcdExtbansPrefix(irc) in item:
                    found = False
                    if self.registryValue('avoidOverlap', channel=channel, network=irc.network):
                        modes = chan.getItemsFor(
                            self.getIrcdMode(irc, mode, item)[0])
                        if len(modes):
                            for m in modes:
                                md = modes[m]
                                if ircutils.isUserHostmask(item):
                                    n = Nick(0)
                                    n.setPrefix(item)
                                    if match(md.value, n, irc, self.registryValue('resolveIp')):
                                        targets.append(md.value)
                                        found = True
                    if not found:
                        targets.append(item)
        n = 0
        for item in targets:
            (m, p) = self.getIrcdMode(irc, mode, item)
            if reason and self.registryValue(
                    'useSmartLog', channel=channel, network=irc.network):
                key = '%s|%s' % (m, p)
                self.smartLog[key] = []
            autoexpire = self.registryValue('autoExpire', channel=channel, network=irc.network)
            if i.add(irc, channel, m, p, duration, autoexpire, msg.prefix, self.getDb(irc.network)):
                if perm:
                    chan = ircdb.channels.getChannel(channel)
                    chan.addBan(p, 0)
                    ircdb.channels.setChannel(channel, chan)
                if reason:
                    f = None
                    if self.registryValue('announceInTimeEditAndMark', channel=channel, network=irc.network) \
                            and ((msg.prefix != irc.prefix and self.registryValue(
                            'announceMark', channel=channel, network=irc.network)) \
                            or (msg.prefix == irc.prefix and self.registryValue(
                            'announceBotMark', channel=channel, network=irc.network))):
                        f = self._logChan
                    i.submark(irc, channel, mode, item, reason, msg.prefix,
                        self.getDb(irc.network), self._logChan, self)
                n += 1
        self.forceTickle = True
        self._tickle(irc)
        return len(items) <= n

    def _removes(self, irc, msg, args, channel, mode, items, perm=False):
        i = self.getIrc(irc)
        chan = self.getChan(irc, channel)
        targets = set([])
        massremove = False
        count = 0
        LL = chan.getItemsFor(self.getIrcdMode(irc, mode, '*!*@*')[0])
        if mode in self.registryValue('modesToAsk', channel=channel, network=irc.network) \
                or mode in self.registryValue('modesToAskWhenOpped', channel=channel, network=irc.network):
            for item in items:
                if item in i.nicks or item in irc.state.channels[channel].users:
                    n = self.getNick(irc, item)
                    # here we check active items against Nick and add each pattern that matches them
                    L = chan.getItemsFor(self.getIrcdMode(irc, mode, n.prefix)[0])
                    for pattern in L:
                        m = match(L[pattern].value, n, irc, self.registryValue('resolveIp'))
                        if m:
                            targets.add(L[pattern].value)
                elif ircutils.isUserHostmask(item) or self.getIrcdExtbansPrefix(irc) in item:
                    # previously we were adding directly the item to remove, now we check it against the active list
                    # that allows to uq $a:* and delete all the quiets on $a:something
                    for pattern in LL:
                        if ircutils.hostmaskPatternEqual(item, LL[pattern].value):
                            targets.add(LL[pattern].value)
                elif item == '*':
                    massremove = True
                    targets = set([])
                    if channel in list(irc.state.channels.keys()):
                        L = chan.getItemsFor(self.getIrcdMode(irc, mode, '*!*@*')[0])
                        for pattern in L:
                            targets.add(L[pattern].value)
                    break
            f = None
            if (massremove and self.registryValue('announceMassRemoval',
                    channel=channel, network=irc.network)) \
                    or (msg.prefix != irc.prefix and self.registryValue(
                    'announceEdit', channel=channel, network=irc.network)) \
                    or (msg.prefix == irc.prefix and self.registryValue(
                    'announceBotEdit', channel=channel, network=irc.network)):
                f = self._logChan
            for item in targets:
                r = self.getIrcdMode(irc, mode, item)
                if perm:
                    chan = ircdb.channels.getChannel(channel)
                    try:
                        chan.removeBan(item)
                    except:
                        log.info('%s is not in Channel.ban' % item)
                    ircdb.channels.setChannel(channel, chan)
                if i.edit(irc, channel, r[0], r[1], 0, msg.prefix, self.getDb(irc.network), None, f, self):
                    count += 1
        self.forceTickle = True
        self._tickle(irc)
        return len(items) <= count or massremove

    def getIrc(self, irc):
        # init irc db
        if irc.network not in self._ircs:
            self._ircs[irc.network] = Ircd(
                irc, self.registryValue('logsSize'))
        return self._ircs[irc.network]

    def getChan(self, irc, channel):
        i = self.getIrc(irc)
        if channel not in i.channels:
            # restore channel state, load lists
            modesToAsk = ''.join(self.registryValue('modesToAsk', channel=channel, network=irc.network))
            modesWhenOpped = ''.join(self.registryValue('modesToAskWhenOpped', channel=channel, network=irc.network))
            if channel in irc.state.channels \
                    and self.registryValue('enabled', channel=channel, network=irc.network):
                if len(modesWhenOpped) and irc.state.channels[channel].isHalfopPlus(irc.nick):
                    for m in modesWhenOpped:
                        i.queue.enqueue(ircmsgs.mode(channel, args=(m,)))
                if len(modesToAsk):
                    for m in modesToAsk:
                        i.lowQueue.enqueue(ircmsgs.mode(channel, args=(m,)))
                if not (self.starting or i.whoxpending):
                    i.whoxpending = True
                    i.lowQueue.enqueue(ircmsgs.who(channel, args=('%tuhnairf,1',)))
                self.forceTickle = True
        return i.getChan(irc, channel)

    def getNick(self, irc, nick, raw=True):
        return self.getIrc(irc).getNick(irc, nick, raw)

    def makeDb(self, filename):
        """Create a database and connect to it."""
        if os.path.exists(filename):
            db = sqlite3.connect(filename, timeout=10)
            if self.dbUpgraded:
                return db
            c = db.cursor()
            try:
                c.execute("""SELECT id,pattern FROM patterns WHERE count=? LIMIT 1""", (0,))
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

    def doPong(self, irc, msg):
        self._tickle(irc)
        i = self.getIrc(irc)
        if not i.whoxpending:
            candidate = None
            for channel in list(irc.state.channels.keys()):
                if not self.registryValue('enabled', channel=channel, network=irc.network):
                    continue
                chan = self.getChan(irc, channel)
                if not chan.syn:
                    candidate = channel
                    break
            if candidate:
                i.whoxpending = True
                irc.queueMsg(ircmsgs.who(candidate, args=('%tuhnairf,1',)))

    def doPing(self, irc, msg):
        self._tickle(irc)

    def _sendModes(self, irc, modes, f):
        numModes = irc.state.supported.get('modes', 1)
        ircd = self.getIrc(irc)
        for i in range(0, len(modes), numModes):
            ircd.queue.enqueue(f(modes[i:i + numModes]))

    def _tickle(self, irc):
        # Called each time messages are received from irc,
        # it avoids using schedulers which can fail silently.
        # For performance, this may be changed in future...
        t = time.time()
        if not self.lastTickle:
            self.lastTickle = t
        if not self.forceTickle:
            pool = self.registryValue('pool')
            if pool > 0 and self.lastTickle+pool > t:
                return
        self.lastTickle = t
        i = self.getIrc(irc)
        retickle = False
        # send waiting msgs, here we mostly got kick messages
        while len(i.queue):
            irc.queueMsg(i.queue.dequeue())
        def f(L):
            return ircmsgs.modes(channel, L)
        for channel in list(irc.state.channels.keys()):
            if not self.registryValue('enabled', channel=channel, network=irc.network):
                    continue
            chan = self.getChan(irc, channel)
            # check expired items
            for mode in list(chan.getItems().keys()):
                for value in list(chan._lists[mode].keys()):
                    item = chan._lists[mode][value]
                    if item.expire is not None and item.expire != item.when \
                            and not item.asked and item.expire <= t:
                        if mode == 'q' and self.registryValue('useChanServForQuiets', channel=channel, network=irc.network) \
                                and not irc.state.channels[channel].isHalfopPlus(irc.nick) \
                                and len(chan.queue) == 0:
                            s = self.registryValue('unquietCommand')
                            s = s.replace('$channel', channel)
                            s = s.replace('$hostmask', item.value)
                            i.queue.enqueue(ircmsgs.IrcMsg(s))
                        else:
                            chan.queue.enqueue(('-%s' % item.mode, item.value))
                        # avoid adding it multiple times until server returns changes
                        item.asked = True
                        retickle = True
            # dequeue pending actions
            # log.debug('[%s] isOpped : %s, opAsked : %s, deopAsked %s, deopPending %s' % (
            #     channel, irc.state.channels[channel].isHalfopPlus(irc.nick), chan.opAsked,
            #     chan.deopAsked,chan.deopPending))
            # if chan.syn: # remove syn mandatory for support of unreal which doesn't like q list
            if len(chan.queue):
                for item in list(chan.queue):
                    (mode, value) = item
                    if mode == '+q' and self.registryValue('useChanServForQuiets', channel=channel, network=irc.network) \
                            and not irc.state.channels[channel].isHalfopPlus(irc.nick) \
                            and len(chan.queue) == 1:
                        s = self.registryValue('quietCommand')
                        s = s.replace('$channel', channel)
                        s = s.replace('$hostmask', value)
                        i.queue.enqueue(ircmsgs.IrcMsg(s))
                        chan.queue.remove(item)
            if not irc.state.channels[channel].isHalfopPlus(irc.nick):
                chan.deopAsked = False
                chan.deopPending = False
            if chan.syn and not (irc.state.channels[channel].isHalfopPlus(irc.nick)
                    or chan.opAsked) and self.registryValue('keepOp', channel=channel, network=irc.network):
                # chan.syn is necessary, otherwise bot can't call owner if rights missed (see doNotice)
                if not self.registryValue('doNothingAboutOwnOpStatus', channel=channel, network=irc.network):
                    chan.opAsked = True
                    def f():
                        chan.opAsked = False
                    schedule.addEvent(f, time.time() + 300)
                    irc.queueMsg(ircmsgs.IrcMsg(self.registryValue('opCommand', channel=channel, network=irc.network).replace(
                        '$channel', channel).replace('$nick', irc.nick)))
                    retickle = True
            if len(chan.queue) or len(chan.action):
                if not (irc.state.channels[channel].isHalfopPlus(irc.nick) or chan.opAsked):
                    # pending actions, but not opped
                    if not chan.deopAsked:
                        if not self.registryValue('doNothingAboutOwnOpStatus', channel=channel, network=irc.network):
                            chan.opAsked = True
                            def f():
                                chan.opAsked = False
                            schedule.addEvent(f, time.time() + 300)
                            irc.queueMsg(ircmsgs.IrcMsg(self.registryValue('opCommand', channel=channel, network=irc.network).replace(
                                '$channel', channel).replace('$nick', irc.nick)))
                            retickle = True
                elif irc.state.channels[channel].isHalfopPlus(irc.nick):
                    if not chan.deopAsked:
                        if len(chan.queue):
                            L = []
                            adding = False
                            for item in list(chan.queue):
                                L.append(item)
                                chan.queue.remove(item)
                                m = item[0][1]
                                if item[0][0] == '+' \
                                        and m in self.registryValue('modesToAsk', channel=channel, network=irc.network) \
                                        and (m in self.registryValue('kickMode', channel=channel, network=irc.network)
                                        or self.registryValue('doActionAgainstAffected', channel=channel, network=irc.network)):
                                    adding = True
                                if m in self.registryValue('modesToAskWhenOpped', channel=channel, network=irc.network):
                                    adding = True
                            # remove duplicates (should not happen, but..)
                            S = set(L)
                            r = []
                            for item in S:
                                r.append(item)
                            # if glitch, just comment this if...
                            if not (len(chan.action) or adding or chan.attacked):
                                if not (self.registryValue('keepOp', channel=channel, network=irc.network)
                                        or self.registryValue('doNothingAboutOwnOpStatus', channel=channel, network=irc.network)):
                                    chan.deopPending = True
                                    chan.deopAsked = True
                                    r.append(('-o', irc.nick))
                            if len(r):
                                # create IrcMsg
                                self._sendModes(irc, r, f)
                        for action in list(chan.action):
                            i.queue.enqueue(action)
                            chan.action.remove(action)
                    else:
                        retickle = True
        # send pending msgs
        while len(i.queue):
            msg = i.queue.dequeue()
            log.info(str(msg))
            irc.queueMsg(msg)
        # update duration
        for channel in list(irc.state.channels.keys()):
            chan = self.getChan(irc, channel)
            # check items to update duration
            # that allows to set mode, and apply duration to Item created after mode changes
            # otherwise, we should create db records before applying mode changes...
            # ...which, well don't do that :p
            if len(chan.update):
                L = list(chan.update.values())
                for update in L:
                    (m, value, expire, prefix) = update
                    # TODO: need to protect cycle call between i.edit scheduler and tickle here
                    item = chan.getItem(m, value)
                    if item and item.expire != expire:
                        f = None
                        if self.registryValue('announceInTimeEditAndMark', channel=channel, network=irc.network) \
                                and ((prefix != irc.prefix and self.registryValue(
                                'announceEdit', channel=item.channel, network=irc.network)) \
                                or (prefix == irc.prefix and self.registryValue(
                                'announceBotEdit', channel=item.channel, network=irc.network))):
                            f = self._logChan
                        b = i.edit(irc, item.channel, item.mode, item.value, expire, prefix,
                            self.getDb(irc.network), self._schedule, f, self)
                        key = '%s|%s' % (m, value)
                        del chan.update[key]
                        retickle = True
            # update marks
            if len(chan.mark):
                L = list(chan.mark.values())
                for mark in L:
                    (m, value, reason, prefix) = mark
                    item = chan.getItem(m, value)
                    if item:
                        f = None
                        if self.registryValue('announceInTimeEditAndMark', channel=channel, network=irc.network) \
                                and ((prefix != irc.prefix and self.registryValue(
                                'announceMark', channel=item.channel, network=irc.network)) \
                                or (prefix == irc.prefix and self.registryValue(
                                'announceBotMark', channel=item.channel, network=irc.network))):
                            f = self._logChan
                        i.mark(irc, item.uid, reason, prefix, self.getDb(irc.network), f, self)
                        key = '%s|%s' % (m, value)
                        del chan.mark[key]
            if irc.state.channels[channel].isHalfopPlus(irc.nick) \
                    and not (self.registryValue('keepOp', channel=channel, network=irc.network)
                    or self.registryValue('doNothingAboutOwnOpStatus', channel=channel, network=irc.network)
                    or chan.deopPending or chan.deopAsked):
                # ask for deop, delay it a bit
                self.unOp(irc, channel)
            # mostly logChannel, and maybe few sync msgs
            if len(i.lowQueue):
                retickle = True
                while len(i.lowQueue):
                    irc.queueMsg(i.lowQueue.dequeue())
        if retickle:
            self.forceTickle = True
        else:
            self.forceTickle = False

    def _addChanModeItem(self, irc, channel, mode, value, prefix, date):
        # bqeI* -ov
        if irc.isChannel(channel) and channel in irc.state.channels:
            if mode in self.registryValue('modesToAsk', channel=channel, network=irc.network) \
                    or mode in self.registryValue('modesToAskWhenOpped', channel=channel, network=irc.network):
                chan = self.getChan(irc, channel)
                item = chan.addItem(mode, value, prefix, float(date),
                    self.getDb(irc.network), False, self)
                # add expiry date if new modes were added when the bot was offline
                expire = self.registryValue('autoExpire', channel=item.channel, network=irc.network)
                if expire > 0 and item.isNew:
                    f = None
                    if self.registryValue('announceBotEdit', channel=item.channel, network=irc.network):
                        f = self._logChan
                    i = self.getIrc(irc)
                    i.edit(irc, item.channel, item.mode, item.value, expire, irc.prefix,
                        self.getDb(irc.network), self._schedule, f, self)
                    item.isNew = False
                    self.forceTickle = True
                item.isNew = False

    def _endList(self, irc, msg, channel, mode):
        if irc.isChannel(channel) and channel in irc.state.channels:
            chan = self.getChan(irc, channel)
            b = False
            if mode not in chan.dones:
                chan.dones.append(mode)
                b = True
            i = self.getIrc(irc)
            f = None
            if self.registryValue('announceModeSync', channel=channel, network=irc.network):
                f = self._logChan
                if b:
                    if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                        f(irc, channel, '[%s] sync %s' % (ircutils.bold(channel), chan.dones))
                    else:
                        f(irc, channel, '[%s] sync %s' % (channel, chan.dones))
            i.resync(irc, channel, mode, self.getDb(irc.network), f, self)
        self._tickle(irc)

    def do346(self, irc, msg):
        # /mode #channel I
        self._addChanModeItem(irc, msg.args[1], 'I', msg.args[2], msg.args[3], msg.args[4])

    def do347(self, irc, msg):
        # end of I list
        self._endList(irc, msg, msg.args[1], 'I')

    def do348(self, irc, msg):
        # /mode #channel e
        self._addChanModeItem(irc, msg.args[1], 'e', msg.args[2], msg.args[3], msg.args[4])

    def do349(self, irc, msg):
        # end of e list
        self._endList(irc, msg, msg.args[1], 'e')

    def do367(self, irc, msg):
        # /mode #channel b
        self._addChanModeItem(irc, msg.args[1], 'b', msg.args[2], msg.args[3], msg.args[4])

    def do368(self, irc, msg):
        # end of b list
        self._endList(irc, msg, msg.args[1], 'b')

    def do728(self, irc, msg):
        # extended mode list (q atm)
        self._addChanModeItem(irc, msg.args[1], msg.args[2], msg.args[3], msg.args[4], msg.args[5])

    def do729(self, irc, msg):
        # end of extended list (q)
        self._endList(irc, msg, msg.args[1], msg.args[2])

    def do352(self, irc, msg):
        # WHO $channel
        (nick, ident, host) = (msg.args[5], msg.args[2], msg.args[3])
        n = self.getNick(irc, nick, raw=True)
        n.setPrefix('%s!%s@%s' % (nick, ident, host))
        chan = self.getChan(irc, msg.args[1])
        chan.nicks[nick] = True
        # channel = msg.args[1]

    def do329(self, irc, msg):
        # channel timestamp
        channel = msg.args[1]
        self._tickle(irc)

    def do354(self, irc, msg):
        # WHO $channel %tnuhiar,42
        # irc.nick 42 ident ip host nick account realname
        if len(msg.args) == 9 and msg.args[1] == '1':
            (garbage, digit, ident, ip, host, nick,
             status, account, realname) = msg.args
            if account == '0':
                account = None
            n = self.getNick(irc, nick, raw=True)
            n.setPrefix('%s!%s@%s' % (nick, ident, host))
            if self.registryValue('resolveIp') and n.ip is None and ip != '255.255.255.255':
                # validate ip
                n.setIp(ip)
            n.setAccount(account)
            n.setRealname(realname)
            #channel = msg.args[1]
        self._tickle(irc)

    def do263(self, irc, msg):
        i = self.getIrc(irc)
        i.whoxpending = False

    def do315(self, irc, msg):
        # end of extended WHO $channel
        channel = msg.args[1]
        if irc.isChannel(channel) and channel in irc.state.channels:
            chan = self.getChan(irc, channel)
            if not chan.syn:
                chan.syn = True
                if self.registryValue('announceModeSync', channel=channel, network=irc.network):
                    if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                        self._logChan(irc, channel, "[%s] is ready" % ircutils.bold(channel))
                    else:
                        self._logChan(irc, channel, "[%s] is ready" % channel)
                for nick in list(irc.state.channels[channel].users):
                    chan.nicks[nick] = True
                i = self.getIrc(irc)
                i.whoxpending = False
                i.lowQueue.enqueue(ircmsgs.ping(channel))
        self._tickle(irc)

    def _logChan(self, irc, channel, message):
        # send messages to logChannel if configured for
        if channel in irc.state.channels:
            logChannel = self.registryValue('logChannel', channel=channel, network=irc.network)
            if logChannel and logChannel in irc.state.channels:
                i = self.getIrc(irc)
                if self.registryValue('announceWithNotice', channel=channel, network=irc.network):
                    i.lowQueue.enqueue(ircmsgs.notice(logChannel, message))
                else:
                    i.lowQueue.enqueue(ircmsgs.privmsg(logChannel, message))
                self.forceTickle = True

    def resolve(self, irc, channels, prefix):
        i = self.getIrc(irc)
        (nick, ident, host) = ircutils.splitHostmask(prefix)
        n = self.getNick(irc, nick)
        if n:
            (nick, ident, host) = ircutils.splitHostmask(n.prefix)
            if not (n.prefix in cache or '/' in host):
                try:
                    r = socket.getaddrinfo(host, None)
                    if r is not None:
                        u = {}
                        L = []
                        for item in r:
                            if item[4][0] not in u:
                                u[item[4][0]] = item[4][0]
                                L.append(item[4][0])
                        if len(L) == 1:
                            n.setIp(L[0])
                except:
                    t = ''
                if n.ip is not None:
                    cache[n.prefix] = n.ip
                else:
                    cache[n.prefix] = host
        self._tickle(irc)

    def doChghost(self, irc, msg):
        n = self.getNick(irc, msg.nick, raw=True)
        (user, host) = msg.args
        hostmask = '%s!%s@%s' % (msg.nick, user, host)
        n.setPrefix(hostmask)
        if 'account' in msg.server_tags:
            n.setAccount(msg.server_tags['account'])

    def doJoin(self, irc, msg):
        channels = msg.args[0].split(',')
        n = self.getNick(irc, msg.nick, raw=True)
        n.setPrefix(msg.prefix)
        i = self.getIrc(irc)
        if len(msg.args) == 3:
            n.setRealname(msg.args[2])
            n.setAccount(msg.args[1])
        if 'account' in msg.server_tags:
            n.setAccount(msg.server_tags['account'])
        if msg.nick == irc.nick:
            self.forceTickle = True
            self._tickle(irc)
            return
        if '/' not in msg.prefix.split('@')[1] and n.ip is None:
            if self.registryValue('resolveIp'):
                t = world.SupyThread(target=self.resolve, name=format(
                    'Resolving %s for %s', msg.prefix, channels), args=(irc, channels, msg.prefix))
                t.setDaemon(True)
                t.start()
            elif utils.net.isIP(msg.prefix.split('@')[1]):
                n.setIp(msg.prefix.split('@')[1])
        for channel in channels:
            if ircutils.isChannel(channel) and channel in irc.state.channels \
                    and self.registryValue('enabled', channel=channel, network=irc.network):
                bests = getBestPattern(n, irc, self.registryValue(
                    'useIpForGateway', channel=channel, network=irc.network), self.registryValue('resolveIp'))
                best = bests[0]
                if self.registryValue('useAccountBanIfPossible', channel=channel, network=irc.network) and n.account:
                    for p in bests:
                        if p.startswith('$a:'):
                            best = p
                            break
                chan = self.getChan(irc, channel)
                chan.nicks[msg.nick] = True
                n.addLog(channel, 'has joined')
                banned = False
                c = ircdb.channels.getChannel(channel)
                if not (self._isVip(irc, channel, n) or chan.netsplit):
                    if c.bans and len(c.bans) \
                            and self.registryValue('useChannelBansForPermanentBan', channel=channel, network=irc.network):
                        for ban in list(c.bans):
                            if match(ban, n, irc, self.registryValue('resolveIp')):
                                autoexpire = self.registryValue('autoExpire', channel=channel, network=irc.network)
                                if i.add(irc, channel, 'b', best, None, autoexpire, irc.prefix, self.getDb(irc.network)):
                                    f = None
                                    if self.registryValue('announceInTimeEditAndMark', channel=channel, network=irc.network) \
                                            and self.registryValue('announceBotMark', channel=channel, network=irc.network):
                                        f = self._logChan
                                    i.submark(irc, channel, 'b', best, "permanent ban %s" % ban,
                                        irc.prefix, self.getDb(irc.network), f, self)
                                    banned = True
                                    self.forceTickle = True
                                    break
                    if not banned:
                        isMassJoin = self._isSomething(irc, channel, channel, 'massJoin')
                        if isMassJoin:
                            if self.registryValue('massJoinMode', channel=channel, network=irc.network) == 'd':
                                if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                                    self._logChan(irc, channel,
                                        '[%s] massJoinMode applied' % ircutils.bold(channel))
                                else:
                                    self._logChan(irc, channel,
                                        '[%s] massJoinMode applied' % channel)
                            else:
                                chan.action.enqueue(ircmsgs.mode(channel,
                                    args=(self.registryValue('massJoinMode', channel=channel, network=irc.network),)))
                            def unAttack():
                                if channel in list(irc.state.channels.keys()):
                                    if self.registryValue('massJoinUnMode', channel=channel, network=irc.network) == 'd':
                                        if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                                            self._logChan(irc, channel,
                                                '[%s] massJoinUnMode applied' % ircutils.bold(channel))
                                        else:
                                            self._logChan(irc, channel,
                                                '[%s] massJoinUnMode applied' % channel)
                                    else:
                                        chan.action.enqueue(ircmsgs.mode(channel,
                                            args=(self.registryValue('massJoinUnMode', channel=channel, network=irc.network),)))
                            schedule.addEvent(unAttack, time.time()
                                + self.registryValue('massJoinDuration', channel=channel, network=irc.network))
                            self.forceTickle = True
                    flag = ircdb.makeChannelCapability(channel, 'clone')
                    if not banned and ircdb.checkCapability(msg.prefix, flag):
                        permit = self.registryValue('clonePermit', channel=channel, network=irc.network)
                        if permit > -1:
                            clones = []
                            for nick in list(irc.state.channels[channel].users):
                                n = self.getNick(irc, nick)
                                m = match(best, n, irc, self.registryValue('resolveIp'))
                                if m:
                                    clones.append(nick)
                            if len(clones) > permit:
                                if self.registryValue('cloneMode', channel=channel, network=irc.network) == 'd':
                                    if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                                        self._logChan(irc, channel, '[%s] clones (%s) detected (%s)' % (
                                            ircutils.bold(channel), best, ', '.join(clones)))
                                    else:
                                        self._logChan(irc, channel, '[%s] clones (%s) detected (%s)' % (
                                            channel, best, ', '.join(clones)))
                                else:
                                    (m, p) = self.getIrcdMode(irc, self.registryValue(
                                        'cloneMode', channel=channel, network=irc.network), best)
                                    self._act(irc, channel, m, p,
                                        self.registryValue('cloneDuration', channel=channel, network=irc.network),
                                        self.registryValue('cloneComment', channel=channel, network=irc.network), msg.nick)
                                    self.forceTickle = True
        self._tickle(irc)

    def doPart(self, irc, msg):
        isBot = msg.prefix == irc.prefix
        channels = msg.args[0].split(',')
        i = self.getIrc(irc)
        n = self.getNick(irc, msg.nick, raw=True)
        n.setPrefix(msg.prefix)
        reason = ''
        if len(msg.args) == 2:
            reason = msg.args[1].strip()
        canRemove = True
        for channel in channels:
            if isBot and channel in i.channels:
                del i.channels[channel]
                continue
            if ircutils.isChannel(channel) and channel in irc.state.channels \
                    and self.registryValue('enabled', channel=channel, network=irc.network):
                bests = getBestPattern(n, irc, self.registryValue(
                    'useIpForGateway', channel=channel, network=irc.network), self.registryValue('resolveIp'))
                best = bests[0]
                if self.registryValue('useAccountBanIfPossible', channel=channel, network=irc.network) and n.account:
                    for p in bests:
                        if p.startswith('$a:'):
                            best = p
                            break
                if len(reason):
                    if reason.startswith('requested by') \
                            and self.registryValue('announceKick', channel=channel, network=irc.network):
                        if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                            self._logChan(irc, channel, '[%s] %s has left (%s)' % (ircutils.bold(
                                channel), ircutils.mircColor(msg.prefix, 'light blue'), reason))
                        else:
                            self._logChan(irc, channel, '[%s] %s has left (%s)' % (
                                channel, msg.prefix, reason))
                        if self.registryValue('addKickMessageInComment', channel=channel, network=irc.network):
                            chan = self.getChan(irc, channel)
                            found = None
                            for mode in self.registryValue('modesToAsk', channel=channel, network=irc.network):
                                items = chan.getItemsFor(mode)
                                for k in items:
                                    item = items[k]
                                    f = match(item.value, n, irc, self.registryValue('resolveIp'))
                                    if f:
                                        found = item
                                        break
                                if found:
                                    break
                            if found:
                                f = None
                                if self.registryValue('announceBotMark', channel=channel, network=irc.network):
                                    f = self._logChan
                                i.mark(irc, found.uid, reason, irc.prefix,
                                    self.getDb(irc.network), f, self)
                    n.addLog(channel, 'has left [%s]' % (reason))
                else:
                    n.addLog(channel, 'has left')
                if not isBot:
                    chan = self.getChan(irc, channel)
                    if msg.nick in chan.nicks:
                        del chan.nicks[msg.nick]
                    if msg.nick in irc.state.channels[channel].users:
                        canRemove = False
                    if not self._isVip(irc, channel, n):
                        isCycle = self._isSomething(irc, channel, best, 'cycle')
                        if isCycle:
                            isBad = self._isSomething(irc, channel, best, 'bad')
                            if isBad:
                                kind = 'bad'
                            else:
                                kind = 'cycle'
                                forward = self.registryValue('cycleForward', channel=channel, network=irc.network)
                                if len(forward):
                                    best += '$%s' % forward
                            mode = self.registryValue('%sMode' % kind, channel=channel, network=irc.network)
                            duration = self.registryValue('%sDuration' % kind, channel=channel, network=irc.network)
                            comment = self.registryValue('%sComment' % kind, channel=channel, network=irc.network)
                            r = self.getIrcdMode(irc, mode, best)
                            self._act(irc, channel, r[0], r[1], duration, comment, msg.nick)
                            self.forceTickle = True
        if canRemove:
            self._rmNick(irc, n)
        self._tickle(irc)

    def doKick(self, irc, msg):
        if len(msg.args) == 3:
            (channel, target, reason) = msg.args
        else:
            (channel, target) = msg.args
            reason = ''
        isBot = target == irc.nick
        if isBot:
            i = self.getIrc(irc)
            if ircutils.isChannel(channel) and channel in i.channels:
                del i.channels[channel]
                self._tickle(irc)
                return
        n = self.getNick(irc, target)
        n.addLog(channel, 'kicked by %s (%s)' % (msg.prefix, reason))
        if self.registryValue('enabled', channel=channel, network=irc.network):
            if self.registryValue('announceKick', channel=channel, network=irc.network):
                if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                    self._logChan(irc, channel, '[%s] %s kicks %s (%s)' % (
                        ircutils.bold(channel), msg.nick,
                        ircutils.mircColor(n.prefix, 'light blue'), reason))
                else:
                    self._logChan(irc, channel, '[%s] %s kicks %s (%s)' % (
                        channel, msg.nick, n.prefix, reason))
            if len(reason) and msg.prefix != irc.prefix \
                    and self.registryValue('addKickMessageInComment', channel=channel, network=irc.network):
                chan = self.getChan(irc, channel)
                found = None
                for mode in self.registryValue('modesToAsk', channel=channel, network=irc.network):
                    items = chan.getItemsFor(mode)
                    for k in items:
                        item = items[k]
                        f = match(item.value, n, irc, self.registryValue('resolveIp'))
                        if f:
                            found = item
                            break
                    if found:
                        break
                if found:
                    f = None
                    if self.registryValue('announceBotMark', channel=channel, network=irc.network):
                        f = self._logChan
                    i = self.getIrc(irc)
                    i.mark(irc, found.uid, 'kicked by %s (%s)' % (
                        msg.nick, reason), irc.prefix, self.getDb(irc.network), f, self)
        if not isBot:
            chan = self.getChan(irc, channel)
            if target in chan.nicks:
                del chan.nicks[target]
        self._tickle(irc)

    def _rmNick(self, irc, n):
        def nrm():
            patterns = getBestPattern(n, irc, self.registryValue(
                'useIpForGateway'), self.registryValue('resolveIp'))
            i = self.getIrc(irc)
            if not len(patterns):
                return
            found = False
            (nick, ident, hostmask) = ircutils.splitHostmask(n.prefix)
            for channel in list(irc.state.channels.keys()):
                if nick in irc.state.channels[channel].users:
                    found = True
            if not found:
                if nick in i.nicks:
                    del i.nicks[nick]
                for channel in list(irc.state.channels.keys()):
                    if not self.registryValue('enabled', channel=channel, network=irc.network):
                        continue
                    bests = getBestPattern(n, irc, self.registryValue(
                        'useIpForGateway', channel=channel, network=irc.network), self.registryValue('resolveIp'))
                    best = bests[0]
                    if self.registryValue('useAccountBanIfPossible', channel=channel, network=irc.network) and n.account:
                        for p in bests:
                            if p.startswith('$a:'):
                                best = p
                                break
                    if channel in i.channels:
                        chan = self.getChan(irc, channel)
                        if nick in chan.nicks:
                            del chan.nicks[nick]
                        if best in chan.repeatLogs:
                            del chan.repeatLogs[best]
                        for k in chan.spam:
                            if best in chan.spam[k]:
                                del chan.spam[k][best]
        schedule.addEvent(nrm, time.time()+self.registryValue('cycleLife')+10)

    def _split(self, irc, channel):
        chan = self.getChan(irc, channel)
        if not chan.netsplit:
            def f(L):
                return ircmsgs.modes(channel, L)
            def d():
                chan.netsplit = False
                unmodes = self.registryValue('netsplitUnmodes', channel=channel, network=irc.network)
                if len(unmodes):
                    if unmodes == 'd':
                        if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                            self._logChan(irc, channel,
                                '[%s] netsplitUnmodes applied' % ircutils.bold(channel))
                        else:
                            self._logChan(irc, channel,
                                '[%s] netsplitUnmodes applied' % channel)
                    else:
                        chan.action.enqueue(ircmsgs.mode(channel, args=(unmodes,)))
                    self.forceTickle = True
                    self._tickle(irc)
            chan.netsplit = True
            schedule.addEvent(d, time.time()+self.registryValue('netsplitDuration', channel=channel, network=irc.network)+1)
            modes = self.registryValue('netsplitModes', channel=channel, network=irc.network)
            if len(modes):
                if modes == 'd':
                    if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                        self._logChan(irc, channel,
                            '[%s] netsplitModes applied' % ircutils.bold(channel))
                    else:
                        self._logChan(irc, channel,
                            '[%s] netsplitModes applied' % channel)
                else:
                    chan.action.enqueue(ircmsgs.mode(channel, args=(modes,)))
                self.forceTickle = True
                self._tickle(irc)

    def doQuit(self, irc, msg):
        isBot = msg.nick == irc.nick
        reason = None
        if len(msg.args) == 1:
            reason = msg.args[0].strip()
        if reason and reason == '*.net *.split':
            for channel in list(irc.state.channels.keys()):
                if not self.registryValue('enabled', channel=channel, network=irc.network):
                    continue
                chan = self.getChan(irc, channel)
                if msg.nick in chan.nicks and not chan.netsplit:
                    self._split(irc, channel)
        removeNick = True
        if isBot:
            self._ircs = ircutils.IrcDict()
            return
        if not isBot:
            n = self.getNick(irc, msg.nick, raw=True)
            n.setPrefix(msg.prefix)
            bests = getBestPattern(n, irc, self.registryValue(
                'useIpForGateway'), self.registryValue('resolveIp'))
            best = None
            if len(bests):
                best = bests[0]
            if not best:
                return
            if reason:
                n.addLog('ALL', 'has quit [%s]' % reason)
            else:
                n.addLog('ALL', 'has quit')
            if not reason:
                pass
            # , 'Excess Flood', 'Max SendQ exceeded'
            elif reason in ('Changing host'):
                # keeping this nick, may trigger cycle check
                removeNick = False
            elif reason.startswith(('Killed (', 'K-Lined')):
                if not ('Nickname regained by services' in reason
                        or 'NickServ (GHOST command used by ' in reason
                        or 'NickServ (Forcing logout ' in reason):
                    for channel in list(irc.state.channels.keys()):
                        if not self.registryValue('enabled', channel=channel, network=irc.network):
                            continue
                        chan = self.getChan(irc, channel)
                        if msg.nick in chan.nicks:
                            if self.registryValue('announceKick', channel=channel, network=irc.network):
                                if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                                    self._logChan(irc, channel, '[%s] %s has quit (%s)' % (
                                        ircutils.bold(channel),
                                        ircutils.mircColor(msg.prefix, 'light blue'),
                                        ircutils.mircColor(reason, 'red')))
                                else:
                                    self._logChan(irc, channel, '[%s] %s has quit (%s)' % (
                                        channel, msg.prefix, reason))
            for channel in list(irc.state.channels.keys()):
                if not self.registryValue('enabled', channel=channel, network=irc.network):
                    continue
                chan = self.getChan(irc, channel)
                if msg.nick in chan.nicks:
                    if not self._isVip(irc, channel, n):
                        bests = getBestPattern(n, irc, self.registryValue(
                            'useIpForGateway', channel=channel, network=irc.network), self.registryValue('resolveIp'))
                        best = bests[0]
                        if self.registryValue('useAccountBanIfPossible', channel=channel, network=irc.network) and n.account:
                            for p in bests:
                                if p.startswith('$a:'):
                                    best = p
                                    break
                        isCycle = self._isSomething(irc, channel, best, 'cycle')
                        if isCycle:
                            isBad = self._isSomething(irc, channel, best, 'bad')
                            if isBad:
                                kind = 'bad'
                            else:
                                kind = 'cycle'
                                forward = self.registryValue('cycleForward', channel=channel, network=irc.network)
                                if len(forward):
                                    best += '$%s' % forward
                            mode = self.registryValue('%sMode' % kind, channel=channel, network=irc.network)
                            duration = self.registryValue('%sDuration' % kind, channel=channel, network=irc.network)
                            comment = self.registryValue('%sComment' % kind, channel=channel, network=irc.network)
                            r = self.getIrcdMode(irc, mode, best)
                            self._act(irc, channel, r[0], r[1], duration, comment, msg.nick)
                            self.forceTickle = True
            if removeNick:
                i = self.getIrc(irc)
                if msg.nick in i.nicks:
                    n = i.nicks[msg.nick]
                    self._rmNick(irc, n)
            self._tickle(irc)

    def doNick(self, irc, msg):
        oldNick = msg.prefix.split('!')[0]
        newNick = msg.args[0]
        i = self.getIrc(irc)
        if oldNick in i.nicks:
            n = self.getNick(irc, oldNick, raw=True)
            del i.nicks[oldNick]
            i.nicks[newNick] = n
            n = self.getNick(irc, newNick, raw=True)
            prefixNew = '%s!%s' % (newNick, msg.prefix.split('!')[1])
            n.setPrefix(prefixNew)
            n.addLog('ALL', '%s is now known as %s' % (oldNick, newNick))
            best = None
            patterns = getBestPattern(n, irc, self.registryValue(
                'useIpForGateway'), self.registryValue('resolveIp'))
            if len(patterns):
                best = patterns[0]
            if not best:
                return
            for channel in list(irc.state.channels.keys()):
                if not self.registryValue('enabled', channel=channel, network=irc.network):
                    continue
                bests = getBestPattern(n, irc, self.registryValue(
                    'useIpForGateway', channel=channel, network=irc.network), self.registryValue('resolveIp'))
                best = bests[0]
                if self.registryValue('useAccountBanIfPossible', channel=channel, network=irc.network) and n.account:
                    for p in bests:
                        if p.startswith('$a:'):
                            best = p
                            break
                if newNick in irc.state.channels[channel].users:
                    chan = self.getChan(irc, channel)
                    if oldNick in chan.nicks:
                        del chan.nicks[oldNick]
                    chan.nicks[msg.nick] = True
                    if self._isVip(irc, channel, n):
                        continue
                    isNick = self._isSomething(irc, channel, best, 'nick')
                    if isNick:
                        isBad = self._isBad(irc, channel, best)
                        if isBad:
                            kind = 'bad'
                        else:
                            kind = 'nick'
                        mode = self.registryValue('%sMode' % kind, channel=channel, network=irc.network)
                        duration = self.registryValue('%sDuration' % kind, channel=channel, network=irc.network)
                        comment = self.registryValue('%sComment' % kind, channel=channel, network=irc.network)
                        if len(mode) > 1:
                            mode = mode[0]
                        r = self.getIrcdMode(irc, mode, best)
                        self._act(irc, channel, r[0], r[1], duration, comment, newNick)
                        self.forceTickle = True
        self._tickle(irc)

    def doCap(self, irc, msg):
        self._tickle(irc)

    def doAccount(self, irc, msg):
        # update nick's model
        n = None
        nick = None
        if ircutils.isUserHostmask(msg.prefix):
            nick = msg.nick
            n = self.getNick(irc, nick, raw=True)
            n.setPrefix(msg.prefix)
            acc = msg.args[0]
            old = n.account
            if acc == '*':
                acc = None
            n.setAccount(acc)
            n.addLog('ALL', '%s is now identified as %s' % (old, acc))
        else:
            return
        if nick and n and n.account and n.ip:
            i = self.getIrc(irc)
            for channel in list(irc.state.channels.keys()):
                if self.registryValue('enabled', channel=channel, network=irc.network) \
                        and self.registryValue('checkEvade', channel=channel, network=irc.network):
                    if nick in irc.state.channels[channel].users:
                        modes = self.registryValue('modesToAsk', channel=channel, network=irc.network)
                        found = None
                        chan = self.getChan(irc, channel)
                        for mode in modes:
                            if mode == 'b':
                                items = chan.getItemsFor(mode)
                                for item in items:
                                    # only check against ~a:,$a: bans
                                    if items[item].value.startswith(self.getIrcdExtbansPrefix(irc)) \
                                            and items[item].value[1] == 'a':
                                        f = match(items[item].value, n, irc, self.registryValue('resolveIp'))
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
                            pattern = getBestPattern(n, irc, self.registryValue('useIpForGateway', channel=channel,
                                network=irc.network), self.registryValue('resolveIp'))[0]
                            r = self.getIrcdMode(irc, found.mode, pattern)
                            self._act(irc, channel, r[0], r[1], duration, 'evade of [#%s +%s %s]' % (
                                found.uid, found.mode, found.value), nick)
                            f = None
                            if self.registryValue('announceBotMark', channel=found.channel, network=irc.network):
                                f = self._logChan
                            i.mark(irc, found.uid, 'evade with %s --> %s' % (msg.prefix, pattern),
                                irc.prefix, self.getDb(irc.network), f, self)
                            self.forceTickle = True
        self._tickle(irc)

    def doNotice(self, irc, msg):
        (targets, text) = msg.args
        if not ircutils.isUserHostmask(irc.prefix):
            return
        if targets == irc.nick:
            b = False
        else:
            if msg.nick == irc.nick:
                return
            n = self.getNick(irc, msg.nick, raw=True)
            n.setPrefix(msg.prefix)
            if 'account' in msg.server_tags:
                n.setAccount(msg.server_tags['account'])
            patterns = getBestPattern(n, irc, self.registryValue(
                'useIpForGateway'), self.registryValue('resolveIp'))
            best = None
            if len(patterns):
                best = patterns[0]
            if not best:
                return
            for channel in targets.split(','):
                if channel.startswith('@'):
                    channel = channel.replace('@', '', 1)
                if channel.startswith('+'):
                    channel = channel.replace('+', '', 1)
                if irc.isChannel(channel) and channel in irc.state.channels \
                        and self.registryValue('enabled', channel=channel, network=irc.network):
                    bests = getBestPattern(n, irc, self.registryValue(
                        'useIpForGateway', channel=channel, network=irc.network), self.registryValue('resolveIp'))
                    best = bests[0]
                    if self.registryValue('useAccountBanIfPossible', channel=channel, network=irc.network) and n.account:
                        for p in bests:
                            if p.startswith('$a:'):
                                best = p
                                break
                    chan = self.getChan(irc, channel)
                    n.addLog(channel, 'NOTICE | %s' % text)
                    if not self._isVip(irc, channel, n):
                        isNotice = self._isSomething(irc, channel, best, 'notice')
                        isBad = False
                        if isNotice:
                            isBad = self._isSomething(irc, channel, best, 'bad')
                        if isNotice or isBad:
                            if isBad:
                                kind = 'bad'
                            else:
                                kind = 'notice'
                            mode = self.registryValue('%sMode' % kind, channel=channel, network=irc.network)
                            duration = self.registryValue('%sDuration' % kind, channel=channel, network=irc.network)
                            comment = self.registryValue('%sComment' % kind, channel=channel, network=irc.network)
                            (m, p) = self.getIrcdMode(irc, mode, best)
                            self._act(irc, channel, m, p, duration, comment, msg.nick)
                            self.forceTickle = True
                        if self.registryValue('announceNotice', channel=channel, network=irc.network):
                            if not chan.isWrong(best):
                                if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                                    self._logChan(irc, channel, '[%s] %s notice "%s"' % (ircutils.bold(
                                        channel), ircutils.mircColor(msg.prefix, 'light blue'), text))
                                else:
                                    self._logChan(irc, channel, '[%s] %s notice "%s"' % (
                                        channel, msg.prefix, text))
        self._tickle(irc)

    def _schedule(self, irc, end, force):
        if end > time.time():
            def do():
                self.forceTickle = force
                self._tickle(irc)
            schedule.addEvent(do, end)
        else:
            self._tickle(irc)

    def _isVip(self, irc, channel, n):
        if not n.prefix:
            return False
        if n.prefix == irc.prefix:
            return 'me!'
        if ircdb.checkCapability(n.prefix, 'trusted'):
            return 'trusted'
        if ircdb.checkCapability(n.prefix, 'protected'):
            return 'protected'
        protected = ircdb.makeChannelCapability(channel, 'protected')
        if ircdb.checkCapability(n.prefix, protected):
            return 'protected'
        if self.registryValue('ignoreVoicedUser', channel=channel, network=irc.network) \
                and irc.state.channels[channel].isVoicePlus(n.prefix.split('!')[0]):
            return 'voiced'
        return False

    def doPrivmsg(self, irc, msg):
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
            n = self.getNick(irc, msg.nick, raw=True)
            n.setPrefix(msg.prefix)
            patterns = getBestPattern(n, irc, self.registryValue(
                'useIpForGateway'), self.registryValue('resolveIp'))
            if len(patterns):
                best = patterns[0]
            # if it fails here stacktrace
        if not (n and best):
            # server msgs or plugin reload, or state not ready
            self._tickle(irc)
            return
        if 'account' in msg.server_tags:
            n.setAccount(msg.server_tags['account'])
        for channel in recipients.split(','):
            if channel.startswith('@'):
                channel = channel.replace('@', '', 1)
            if channel.startswith('+'):
                channel = channel.replace('+', '', 1)
            if irc.isChannel(channel) and channel in irc.state.channels \
                    and self.registryValue('enabled', channel=channel, network=irc.network):
                bests = getBestPattern(n, irc, self.registryValue(
                    'useIpForGateway', channel=channel, network=irc.network), self.registryValue('resolveIp'))
                best = bests[0]
                if self.registryValue('useAccountBanIfPossible', channel=channel, network=irc.network) and n.account:
                    for p in bests:
                        if p.startswith('$a:'):
                            best = p
                            break
                chan = self.getChan(irc, channel)
                message = text
                if isCtcpMsg and not isAction:
                    message = 'CTCP | %s' % text
                elif isAction:
                    message = '- %s -' % text
                n.addLog(channel, message)
                # protection features
                if not self._isVip(irc, channel, n):
                    isCtcp = False
                    if isCtcpMsg and not isAction:
                        isCtcp = self._isSomething(irc, channel, best, 'ctcp')
                    flag = ircdb.makeChannelCapability(channel, 'flood')
                    isFlood = False
                    if ircdb.checkCapability(msg.prefix, flag):
                        isFlood = self._isSomething(irc, channel, best, 'flood')
                    flag = ircdb.makeChannelCapability(channel, 'lowFlood')
                    isLowFlood = False
                    if ircdb.checkCapability(msg.prefix, flag):
                        isLowFlood = self._isSomething(irc, channel, best, 'lowFlood')
                    flag = ircdb.makeChannelCapability(channel, 'repeat')
                    isRepeat = False
                    if ircdb.checkCapability(msg.prefix, flag):
                        isRepeat = self._isRepeat(irc, channel, best, text)
                    flag = ircdb.makeChannelCapability(channel, 'hilight')
                    isHilight = False
                    if ircdb.checkCapability(msg.prefix, flag):
                        isHilight = self._isHilight(irc, channel, best, text)
                    flag = ircdb.makeChannelCapability(channel, 'cap')
                    isCap = False
                    if ircdb.checkCapability(msg.prefix, flag):
                        isCap = self._isCap(irc, channel, best, text)
                    flag = ircdb.makeChannelCapability(channel, 'pattern')
                    isPattern = False
                    isMatch = False
                    isTemporaryPattern = False
                    if ircdb.checkCapability(msg.prefix, flag):
                        for p in chan.patterns:
                            pattern = chan.patterns[p]
                            matched = pattern.match(text)
                            if matched[0]:
                                if pattern.limit == 0:
                                    isPattern = pattern
                                    isMatch = matched
                                    break
                                else:
                                    prop = 'Pattern%s' % pattern.uid
                                    key = best
                                    if prop not in chan.spam:
                                        chan.spam[prop] = {}
                                    if key not in chan.spam[prop] \
                                            or chan.spam[prop][key].timeout != pattern.life:
                                        chan.spam[prop][key] = utils.structures.TimeoutQueue(pattern.life)
                                    chan.spam[prop][key].enqueue(key)
                                    if len(chan.spam[prop][key]) > pattern.limit:
                                        chan.spam[prop][key].reset()
                                        isPattern = pattern
                                        isMatch = matched
                                        break
                    if isMatch:
                        (m, p) = self.getIrcdMode(irc, isPattern.mode, best)
                        self._act(irc, channel, m, p, isPattern.duration,
                            'matches #%s: %s' % (isPattern.uid, isMatch[1]), msg.nick)
                        isBad = self._isBad(irc, channel, best)
                        chan.countpattern(isPattern.uid, self.getDb(irc.network))
                        self.forceTickle = True
                    elif not isRepeat:
                        key = 'pattern%s' % channel
                        if key in chan.repeatLogs:
                            patterns = chan.repeatLogs[key]
                            for pattern in patterns:
                                if pattern in text:
                                    isTemporaryPattern = pattern
                                    break
                            if isTemporaryPattern:
                                chan.repeatLogs[key].enqueue(isTemporaryPattern)
                                (m, p) = self.getIrcdMode(irc, self.registryValue(
                                    'repeatMode', channel=channel, network=irc.network), best)
                                # hidden reason matches "%s"' % isTemporaryPattern
                                self._act(irc, channel, m, p, self.registryValue(
                                    'repeatDuration', channel=channel, network=irc.network),
                                    'temporary pattern', msg.nick)
                                isBad = self._isBad(irc, channel, best)
                                self.forceTickle = True
                    if not (isPattern or isTemporaryPattern) \
                            and (isFlood or isLowFlood or isRepeat or isHilight or isCap or isCtcp):
                        isBad = self._isBad(irc, channel, best)
                        duration = 0
                        if isBad:
                            kind = 'bad'
                            duration = self.registryValue('badDuration', channel=channel, network=irc.network)
                        else:
                            if isFlood:
                                d = self.registryValue('floodDuration', channel=channel, network=irc.network)
                                if d > duration:
                                    kind = 'flood'
                                    duration = d
                            if isLowFlood:
                                d = self.registryValue('lowFloodDuration', channel=channel, network=irc.network)
                                if d > duration:
                                    kind = 'lowFlood'
                                    duration = d
                            if isRepeat:
                                d = self.registryValue('repeatDuration', channel=channel, network=irc.network)
                                if d > duration:
                                    kind = 'repeat'
                                    duration = d
                            if isHilight:
                                d = self.registryValue('hilightDuration', channel=channel, network=irc.network)
                                if d > duration:
                                    kind = 'hilight'
                                    duration = d
                            if isCap:
                                d = self.registryValue('capDuration', channel=channel, network=irc.network)
                                if d > duration:
                                    kind = 'cap'
                                    duration = d
                            if isCtcp:
                                d = self.registryValue('ctcpDuration', channel=channel, network=irc.network)
                                if d > duration:
                                    kind = 'ctcp'
                                    duration = d
                        mode = self.registryValue('%sMode' % kind, channel=channel, network=irc.network)
                        comment = self.registryValue('%sComment' % kind, channel=channel, network=irc.network)
                        if len(mode) > 1:
                            mode = mode[0]
                        (m, p) = self.getIrcdMode(irc, mode, best)
                        self._act(irc, channel, m, p, duration, comment, msg.nick)
                        self.forceTickle = True
                if not chan.isWrong(best):
                    # prevent the bot to flood logChannel with bad user craps
                    if self.registryValue('announceCtcp', channel=channel, network=irc.network) and isCtcpMsg and not isAction:
                        if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                            self._logChan(irc, channel, '[%s] %s ctcps "%s"' % (ircutils.bold(
                                channel), ircutils.mircColor(msg.prefix, 'light blue'), text))
                        else:
                            self._logChan(irc, channel, '[%s] %s ctcps "%s"' % (
                                channel, msg.prefix, text))
                        self.forceTickle = True
                    else:
                        if self.registryValue('announceOthers', channel=channel, network=irc.network) \
                                and irc.state.channels[channel].isHalfopPlus(irc.nick) \
                                and 'z' in irc.state.channels[channel].modes:
                            message = None
                            if 'm' in irc.state.channels[channel].modes:
                                if not (msg.nick in irc.state.channels[channel].voices
                                        or irc.state.channels[channel].isHalfopPlus(msg.nick)):
                                    if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                                        message = '[%s] [+m] <%s> %s' % (ircutils.bold(
                                            channel), ircutils.mircColor(msg.prefix, 'light blue'), text)
                                    else:
                                        message = '[%s] [+m] <%s> %s' % (
                                            channel, msg.prefix, text)
                            if not message:
                                if not (msg.nick in irc.state.channels[channel].voices
                                        or irc.state.channels[channel].isHalfopPlus(msg.nick)):
                                    modes = self.registryValue('modesToAsk', channel=channel, network=irc.network)
                                    found = False
                                    for mode in modes:
                                        items = chan.getItemsFor(mode)
                                        for item in items:
                                            f = match(items[item].value, n, irc,
                                                self.registryValue('resolveIp'))
                                            if f:
                                                found = [items[item], f]
                                            if found:
                                                break
                                        if found:
                                            break
                                    if found:
                                        if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                                            message = '[%s] [#%s %s %s] <%s> %s' % (
                                                ircutils.bold(channel), found[0].uid,
                                                ircutils.bold(ircutils.mircColor('+%s' % found[0].mode, 'red')),
                                                ircutils.mircColor(found[0].value, 'light blue'),
                                                msg.nick, text)
                                        else:
                                            message = '[%s] [#%s +%s %s] <%s> %s' % (
                                                channel, found[0].uid, found[0].mode, found[0].value,
                                                msg.nick, text)
                            if message:
                                self._logChan(irc, channel, message)
            elif irc.nick == channel and not (checkAddressed(irc, text, channel)
                    or isCommand(irc.callbacks, text.lower().split())):
                found = self.hasAskedItems(irc, msg.prefix, remove=False, prompt=False)
                if found:
                    tokens = callbacks.tokenize('ChanTracker editAndMark %s %s' % (found[0], text))
                    self.Proxy(irc.irc, msg, tokens)
        self._tickle(irc)

    def hasAskedItems(self, irc, prefix, remove, prompt):
        i = self.getIrc(irc)
        if prefix in i.askedItems:
            found = None
            for item in list(i.askedItems[prefix].values()):
                if (not found or item[0] < found[0]) \
                        and not (prompt and item[6]):
                    found = item
            if found:
                chan = self.getChan(irc, found[3])
                items = chan.getItemsFor(found[1])
                active = None
                if len(items):
                    for item in items:
                        item = items[item]
                        if item.uid == found[0]:
                            active = item
                            break
                if remove:
                    del i.askedItems[prefix][found[0]]
                    if not len(i.askedItems[prefix]):
                        del i.askedItems[prefix]
                if active:
                    return found
        return None

    def addToAsked(self, irc, prefix, data, nick):
        toAsk = False
        i = self.getIrc(irc)
        if prefix not in i.askedItems:
            i.askedItems[prefix] = {}
            toAsk = True
        i.askedItems[prefix][data[0]] = data
        if toAsk:
            i.askedItems[prefix][data[0]][6] = True
            i.lowQueue.enqueue(ircmsgs.privmsg(nick, data[5]))
            self.forceTickle = True
            self._tickle(irc)
        def unAsk():
            if prefix in i.askedItems:
                if data[0] in i.askedItems[prefix]:
                    del i.askedItems[prefix][data[0]]
                if not len(list(i.askedItems[prefix])):
                    del i.askedItems[prefix]
            found = self.hasAskedItems(irc, prefix, remove=False, prompt=True)
            if found:
                i.askedItems[prefix][found[0]][6] = True
                i.lowQueue.enqueue(ircmsgs.privmsg(nick, found[5]))
                self.forceTickle = True
                self._tickle(irc)
        schedule.addEvent(unAsk, time.time() + (300 * len(list(i.askedItems[prefix]))))

    def doTopic(self, irc, msg):
        if len(msg.args) == 1:
            return
        n = None
        if ircutils.isUserHostmask(msg.prefix):
            n = self.getNick(irc, msg.nick, raw=True)
            n.setPrefix(msg.prefix)
            if 'account' in msg.server_tags:
                n.setAccount(msg.server_tags['account'])
        channel = msg.args[0]
        if channel in irc.state.channels \
                and self.registryValue('enabled', channel=channel, network=irc.network):
            if n:
                n.addLog(channel, 'sets topic "%s"' % msg.args[1])
            if self.registryValue('announceTopic', channel=channel, network=irc.network):
                if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                    self._logChan(irc, channel, '[%s] %s sets topic "%s"' % (ircutils.bold(
                        channel), ircutils.mircColor(msg.prefix, 'light blue'), msg.args[1]))
                else:
                    self._logChan(irc, channel, '[%s] %s sets topic "%s"' % (
                        channel, msg.prefix, msg.args[1]))
                self.forceTickle = True
        self._tickle(irc)

    def unOp(self, irc, channel):
        # remove op from irc.nick, if nothing pending
        if channel in irc.state.channels:
            i = self.getIrc(irc)
            chan = self.getChan(irc, channel)
            if chan.deopPending:
                return
            def unOpBot():
                if channel in irc.state.channels \
                        and irc.state.channels[channel].isHalfopPlus(irc.nick) \
                        and not (self.registryValue('keepOp', channel=channel, network=irc.network)
                        or chan.deopAsked):
                    chan.deopPending = False
                    if not (len(i.queue) or len(chan.queue)):
                        chan.deopAsked = True
                        irc.queueMsg(ircmsgs.deop(channel, irc.nick))
                        # little trick here, tickle before setting deopFlag
                        self.forceTickle = True
                        self._tickle(irc)
                    else:
                        # reask for deop
                        self.unOp(irc, channel)
            chan.deopPending = True
            schedule.addEvent(unOpBot, time.time()+10)

    def hasExtendedSharedBan(self, irc, fromChannel, target, mode):
        # TODO: add support for other ircds if possible, currently only freenode
        b = '%sj:%s' % (self.getIrcdExtbansPrefix(irc), fromChannel)
        kicks = []
        for channel in list(irc.state.channels.keys()):
            if not self.registryValue('enabled', channel=channel, network=irc.network):
                continue
            if b in irc.state.channels[channel].bans \
                    and mode in self.registryValue('kickMode', channel=channel, network=irc.network) \
                    and self.registryValue('kickOnMode', channel=channel, network=irc.network):
                for nick in list(irc.state.channels[channel].users):
                    n = self.getNick(irc, nick)
                    isVip = self._isVip(irc, channel, n)
                    if not isVip:
                        m = match(target, n, irc, self.registryValue('resolveIp'))
                        if m:
                            if len(kicks) < self.registryValue('kickMax', channel=channel, network=irc.network):
                                if nick != irc.nick:
                                    kicks.append([nick, channel])
        if len(kicks):
            for kick in kicks:
                chan = self.getChan(irc, kick[1])
                chan.action.enqueue(ircmsgs.kick(kick[1], kick[0], random.choice(
                    self.registryValue('kickMessage', channel=kick[1], network=irc.network))))
            self.forceTickle = True

    def doMode(self, irc, msg):
        channel = msg.args[0]
        now = time.time()
        n = None
        i = self.getIrc(irc)
        if ircutils.isUserHostmask(msg.prefix):
            # prevent server.netsplit to create a Nick
            n = self.getNick(irc, msg.nick, raw=True)
            n.setPrefix(msg.prefix)
            if 'account' in msg.server_tags:
                n.setAccount(msg.server_tags['account'])
        # umode otherwise
        db = self.getDb(irc.network)
        c = db.cursor()
        toCommit = False
        toexpire = []
        tolift = []
        toremove = []
        if irc.isChannel(channel) and msg.args[1:] and channel in irc.state.channels \
                and self.registryValue('enabled', channel=channel, network=irc.network):
            modes = ircutils.separateModes(msg.args[1:])
            chan = self.getChan(irc, channel)
            msgs = []
            announces = self.registryValue('announceModes', channel=channel, network=irc.network)
            autoexpire = self.registryValue('autoExpire', channel=channel, network=irc.network)
            for change in modes:
                (mode, value) = change
                m = mode[1]
                if value:
                    value = str(value).strip()
                    item = None
                    if mode[0] == '+':
                        if m in self.registryValue('modesToAsk', channel=channel, network=irc.network) \
                                or m in self.registryValue('modesToAskWhenOpped', channel=channel, network=irc.network):
                            item = chan.addItem(m, value, msg.prefix, now, self.getDb(irc.network),
                                self.registryValue('trackAffected', channel=channel, network=irc.network), self)
                            if msg.nick != irc.nick and self.registryValue('askOpAboutMode', channel=channel, network=irc.network) \
                                    and ircdb.checkCapability(msg.prefix, '%s,op' % channel):
                                message = 'For [#%s %s %s in %s - %s user(s)] <duration> <reason>, ' \
                                    + 'you have 5 minutes (example: 10m offtopic)'
                                if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                                    message = message % (
                                        ircutils.mircColor(item.uid, 'yellow', 'black'),
                                        ircutils.bold(ircutils.mircColor('+%s' % m, 'red')),
                                        ircutils.mircColor(value, 'light blue'), channel, len(item.affects))
                                else:
                                    message = message % (
                                        item.uid, '+%s' % m, value, channel, len(item.affects))
                                data = [item.uid, m, value, channel, msg.prefix, message, False]
                                self.addToAsked(irc, msg.prefix, data, msg.nick)
                            if autoexpire > 0:
                                if msg.nick != irc.nick:
                                    toexpire.append(item)
                        # here bot could add other mode changes or actions
                        if item and len(item.affects):
                            for affected in item.affects:
                                nick = affected.split('!')[0]
                                n = self.getNick(irc, nick)
                                isVip = self._isVip(irc, channel, n)
                                if isVip:
                                    continue
                                if m in self.registryValue('modesToAsk', channel=channel, network=irc.network) \
                                        and self.registryValue('doActionAgainstAffected', channel=channel, network=irc.network) \
                                        and irc.nick != nick:
                                    for k in list(chan.getItems()):
                                        if k in self.registryValue('modesToAskWhenOpped', channel=channel, network=irc.network):
                                            items = chan.getItemsFor(k)
                                            if len(items):
                                                for active in items:
                                                    active = items[active]
                                                    if match(active.value, n, irc, self.registryValue('resolveIp')):
                                                        tolift.append(active)
                                kicked = False
                                # and not value.startswith(self.getIrcdExtbans(irc)) works for unreal
                                if m in self.registryValue('kickMode', channel=channel, network=irc.network) \
                                        and not value.startswith('m:'):
                                    if msg.nick in (irc.nick, 'ChanServ') \
                                            or self.registryValue('kickOnMode', channel=channel, network=irc.network):
                                        kickMax = self.registryValue('kickMax', channel=channel, network=irc.network)
                                        if (kickMax < 0 or kickMax > len(item.affects)) \
                                                and nick in irc.state.channels[channel].users \
                                                and nick != irc.nick:
                                            km = random.choice(self.registryValue('kickMessage', channel=channel, network=irc.network))
                                            if msg.nick in (irc.nick, 'ChanServ'):
                                                if self.registryValue('discloseOperator', channel=channel, network=irc.network):
                                                    hk = '%s|%s' % (m, value)
                                                    if hk in chan.update and len(chan.update[hk]) == 4:
                                                        if ircutils.isUserHostmask(chan.update[hk][3]):
                                                            (nn, ii, hh) = ircutils.splitHostmask(chan.update[hk][3])
                                                            if nn != irc.nick:
                                                                km += ' (by %s)' % nn
                                            chan.action.enqueue(ircmsgs.kick(channel, nick, km))
                                            self.forceTickle = True
                                            kicked = True
                                if m == 'b' and not (kicked or chan.attacked):
                                    if msg.nick in (irc.nick, 'ChanServ'):
                                        bm = self.registryValue('banMessage', channel=channel, network=irc.network)
                                        if len(bm):
                                            if self.registryValue('discloseOperator', channel=channel, network=irc.network):
                                                hk = '%s|%s' % (m, value)
                                                if hk in chan.update and len(chan.update[hk]) == 4:
                                                    if ircutils.isUserHostmask(chan.update[hk][3]):
                                                        (nn, ii, hh) = ircutils.splitHostmask(chan.update[hk][3])
                                                        if nn != irc.nick:
                                                            bm += ' (by %s)' % nn
                                                        elif self.registryValue('proxyMsgOnly', channel=channel, network=irc.network):
                                                            bm = ''
                                            if len(bm):
                                                bm = bm.replace('$channel', channel)
                                                log.info('[%s] warned %s with: %s' % (channel, nick, bm))
                                                if self.registryValue('banNotice', channel=channel, network=irc.network):
                                                    i.lowQueue.enqueue(ircmsgs.notice(nick, bm))
                                                else:
                                                    i.lowQueue.enqueue(ircmsgs.privmsg(nick, bm))
                                if m == 'q' and not (kicked or chan.attacked or value == '$~a'):
                                    if msg.nick in (irc.nick, 'ChanServ'):
                                        qm = self.registryValue('quietMessage', channel=channel, network=irc.network)
                                        if len(qm):
                                            if self.registryValue('discloseOperator', channel=channel, network=irc.network):
                                                hk = '%s|%s' % (m, value)
                                                if hk in chan.update and len(chan.update[hk]) == 4:
                                                    if ircutils.isUserHostmask(chan.update[hk][3]):
                                                        (nn, ii, hh) = ircutils.splitHostmask(chan.update[hk][3])
                                                        if nn != irc.nick:
                                                            qm += ' (by %s)' % nn
                                                        elif self.registryValue('proxyMsgOnly', channel=channel, network=irc.network):
                                                            qm = ''
                                            if len(qm):
                                                qm = qm.replace('$channel', channel)
                                                log.info('[%s] warned %s with: %s' % (channel, nick, qm))
                                                if self.registryValue('quietNotice', channel=channel, network=irc.network):
                                                    i.lowQueue.enqueue(ircmsgs.notice(nick, qm))
                                                else:
                                                    i.lowQueue.enqueue(ircmsgs.privmsg(nick, qm))
                                if not kicked and m in self.registryValue('modesToAsk', channel=channel, network=irc.network) \
                                        and self.registryValue('doActionAgainstAffected', channel=channel, network=irc.network) \
                                        and msg.nick in (irc.nick, 'ChanServ') and nick != irc.nick:
                                    if nick in irc.state.channels[channel].ops:
                                        chan.queue.enqueue(('-o', nick))
                                    if nick in irc.state.channels[channel].halfops:
                                        chan.queue.enqueue(('-h', nick))
                                    if nick in irc.state.channels[channel].voices:
                                        chan.queue.enqueue(('-v', nick))
                        if m in self.registryValue('kickMode', channel=channel, network=irc.network) \
                                and self.registryValue('kickOnMode', channel=channel, network=irc.network) \
                                and not value.startswith('m:'):
                            self.hasExtendedSharedBan(irc, channel, value, m)
                        # bot just got op
                        if m == 'o' and value == irc.nick:
                            chan.opAsked = False
                            chan.deopPending = False
                            ms = ''
                            asked = self.registryValue('modesToAskWhenOpped', channel=channel, network=irc.network)
                            asked = ''.join(asked)
                            asked = asked.replace(',', '')
                            for k in asked:
                                if k not in chan.dones:
                                    irc.queueMsg(ircmsgs.mode(channel, args=(k,)))
                            # flush pending queue, if items are waiting
                            self.forceTickle = True
                    else:
                        if m == 'o' and value == irc.nick:
                            # prevent bot from sending many -o modes when server takes time to reply
                            chan.deopAsked = False
                        if m in self.registryValue('modesToAsk', channel=channel, network=irc.network) \
                                or m in self.registryValue('modesToAskWhenOpped', channel=channel, network=irc.network):
                            toCommit = True
                            item = chan.removeItem(m, value, msg.prefix, c)
                            if item and item.channel == channel:
                                toremove.append(item)
                    if n:
                        n.addLog(channel, 'sets %s %s' % (mode, value))
                    if item:
                        if mode[0] == '+':
                            if not len(item.affects):
                                if m in announces:
                                    if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                                        msgs.append('[#%s %s %s]' % (
                                            ircutils.mircColor(item.uid, 'yellow', 'black'),
                                            ircutils.bold(ircutils.mircColor(mode, 'red')),
                                            ircutils.mircColor(value, 'light blue')))
                                    else:
                                        msgs.append('[#%s %s %s]' % (
                                            item.uid, mode, value))
                            elif len(item.affects) > 1:
                                if m in announces:
                                    if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                                        msgs.append('[#%s %s %s - %s users]' % (
                                            ircutils.mircColor(item.uid, 'yellow', 'black'),
                                            ircutils.bold(ircutils.mircColor(mode, 'red')),
                                            ircutils.mircColor(value, 'light blue'),
                                            len(item.affects)))
                                    else:
                                        msgs.append('[#%s %s %s - %s users]' % (
                                            item.uid, mode, value, len(item.affects)))
                            else:
                                if m in announces:
                                    if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                                        msgs.append('[#%s %s %s - %s]' % (
                                            ircutils.mircColor(item.uid, 'yellow', 'black'),
                                            ircutils.bold(ircutils.mircColor(mode, 'red')),
                                            ircutils.mircColor(value, 'light blue'), item.affects[0]))
                                    else:
                                        msgs.append('[#%s %s %s - %s]' % (
                                            item.uid, mode, value, item.affects[0]))
                        else:
                            if not len(item.affects):
                                if m in announces:
                                    if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                                        msgs.append('[#%s %s %s - %s]' % (
                                            ircutils.mircColor(item.uid, 'yellow', 'black'),
                                            ircutils.bold(ircutils.mircColor(mode, 'green')),
                                            ircutils.mircColor(value, 'light blue'),
                                            utils.timeElapsed(item.removed_at-item.when)))
                                    else:
                                        msgs.append('[#%s %s %s - %s]' % (
                                            item.uid, mode, value,
                                            utils.timeElapsed(item.removed_at-item.when)))
                            elif len(item.affects) > 1:
                                if m in announces:
                                    if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                                        msgs.append('[#%s %s %s - %s users, %s]' % (
                                            ircutils.mircColor(item.uid, 'yellow', 'black'),
                                            ircutils.bold(ircutils.mircColor(mode, 'green')),
                                            ircutils.mircColor(value, 'light blue'), len(item.affects),
                                            utils.timeElapsed(item.removed_at-item.when)))
                                    else:
                                        msgs.append('[#%s %s %s - %s users, %s]' % (
                                            item.uid, mode, value, len(item.affects),
                                            utils.timeElapsed(item.removed_at-item.when)))
                            else:
                                if m in announces:
                                    if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                                        msgs.append('[#%s %s %s - %s, %s]' % (
                                            ircutils.mircColor(item.uid, 'yellow', 'black'),
                                            ircutils.bold(ircutils.mircColor(mode, 'green')),
                                            ircutils.mircColor(value, 'light blue'), item.affects[0],
                                            utils.timeElapsed(item.removed_at-item.when)))
                                    else:
                                        msgs.append('[#%s %s %s - %s, %s]' % (
                                            item.uid, mode, value, item.affects[0],
                                            utils.timeElapsed(item.removed_at-item.when)))
                    else:
                        if m in announces:
                            if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                                if mode[0] == '+':
                                    msgs.append('[%s %s]' % (ircutils.bold(ircutils.mircColor(
                                        mode, 'red')), ircutils.mircColor(value, 'light blue')))
                                else:
                                    msgs.append('[%s %s]' % (ircutils.bold(ircutils.mircColor(
                                        mode, 'green')), ircutils.mircColor(value, 'light blue')))
                            else:
                                msgs.append('[%s %s]' % (mode, value))
                else:
                    if n:
                        n.addLog(channel, 'sets %s' % mode)
                    if m in announces:
                        if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                            if mode[0] == '+':
                                msgs.append(ircutils.bold(ircutils.mircColor(mode, 'red')))
                            else:
                                msgs.append(ircutils.bold(ircutils.mircColor(mode, 'green')))
                        else:
                            msgs.append(mode)
            if toCommit:
                db.commit()
            if len(toremove):
                for r in toremove:
                    i.verifyRemoval(irc, r.channel, r.mode, r.value, db, self, r.uid)
            if irc.state.channels[channel].isHalfopPlus(irc.nick) \
                    and not self.registryValue('keepOp', channel=channel, network=irc.network):
                self.forceTickle = True
            if len(self.registryValue('announceModes', channel=channel, network=irc.network)) and len(msgs):
                if self.registryValue('announceModeMadeByIgnored', channel=channel, network=irc.network) \
                        or not ircdb.checkIgnored(msg.prefix, channel):
                    if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                        message = '[%s] %s sets %s' % (ircutils.bold(channel), msg.nick, ' '.join(msgs))
                    else:
                        message = '[%s] %s sets %s' % (channel, msg.nick, ' '.join(msgs))
                    key = '%s|%s' % (m, value)
                    if key in self.smartLog:
                        self.smartLog[key].append(message)
                    else:
                        self._logChan(irc, channel, message)
                    self.forceTickle = True
            if len(toexpire):
                for item in toexpire:
                    f = None
                    if self.registryValue('announceBotEdit', channel=item.channel, network=irc.network):
                        f = self._logChan
                    i.edit(irc, item.channel, item.mode, item.value, self.registryValue(
                        'autoExpire', channel=item.channel, network=irc.network), irc.prefix,
                        self.getDb(irc.network), self._schedule, f, self)
                self.forceTickle = True
            if len(tolift):
                for item in tolift:
                    f = None
                    if self.registryValue('announceBotEdit', channel=item.channel, network=irc.network):
                        f = self._logChan
                    i.edit(irc, item.channel, item.mode, item.value, 0, irc.prefix,
                        self.getDb(irc.network), self._schedule, f, self)
                self.forceTickle = True
        c.close()
        # as tickle now may be a bit too early, delay it a bit
        def ttickle():
            self._tickle(irc)
        schedule.addEvent(ttickle, time.time()+1)

    def do474(self, irc, msg):
        # bot banned from a channel it is trying to join
        # server 474 irc.nick #channel :Cannot join channel (+b) - you are banned
        # TODO: talk with owner
        self._tickle(irc)

    def do478(self, irc, msg):
        # message when ban list is full after adding something to eqIb list
        channel = msg.args[1]
        info = msg.args[3]
        logChannel = self.registryValue('logChannel', channel=channel, network=irc.network)
        if logChannel and logChannel in irc.state.channels:
            ops = []
            for nick in list(irc.state.channels[logChannel].users):
                if nick != irc.nick:
                    n = self.getNick(irc, nick)
                    if n.prefix and (ircdb.checkCapability(n.prefix, 'owner') or
                            ircdb.checkCapability(n.prefix, '%s,op' % channel)):
                        ops.append(nick)
            if ops:
                if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                    self._logChan(irc, channel, '[%s] %s: %s' % (ircutils.bold(
                        channel), ircutils.bold(ircutils.mircColor(info, 'red')), ', '.join(ops)))
                else:
                    self._logChan(irc, channel, '[%s] %s: %s' % (
                        channel, info, ', '.join(ops)))
        self._tickle(irc)

    # protection features
    def _act(self, irc, channel, mode, mask, duration, reason, nick):
        log.info('ChanTracker: acting in %s against %s / %s : %s %s %s' % (channel, nick, mask, mode, duration, reason))
        if self.registryValue('ignoreOnAbuse', channel=channel, network=irc.network):
            c = ircdb.channels.getChannel(channel)
            c.addIgnore(mask, time.time() + duration)
            ircdb.channels.setChannel(channel, c)
        if mode == 'D':
            action = self.registryValue('modeD')
            if len(action):
                s = action
                s = s.replace('$channel', channel)
                s = s.replace('$hostmask', mask)
                (n, i, h) = ircutils.splitHostmask(mask)
                klinemask = '%s@%s' % (i, h)
                s = s.replace('$klinemask', klinemask)
                s = s.replace('$host', h)
                s = s.replace('$duration', str(duration))
                s = s.replace('$reason', reason)
                s = s.replace('$nick', nick)
                irc.queueMsg(ircmsgs.IrcMsg(s))
            return
        if mode == 'd':
            if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                self._logChan(irc, channel, '[%s] debug %s %s %s %s' % (
                    ircutils.bold(channel), mode, ircutils.mircColor(mask, 'teal'),
                    ircutils.bold(duration), reason))
            else:
                self._logChan(irc, channel, '[%s] debug %s %s %s %s' % (
                    channel, mode, mask, duration, reason))
            self.forceTickle = True
            self._tickle(irc)
            return
        if mode in self.registryValue('modesToAsk', channel=channel, network=irc.network) \
                or mode in self.registryValue('modesToAskWhenOpped', channel=channel, network=irc.network):
            i = self.getIrc(irc)
            autoexpire = self.registryValue('autoExpire', channel=channel, network=irc.network)
            if i.add(irc, channel, mode, mask, duration, autoexpire, irc.prefix, self.getDb(irc.network)):
                if reason and len(reason):
                    f = None
                    if self.registryValue('announceInTimeEditAndMark', channel=channel, network=irc.network) \
                            and self.registryValue('announceBotMark', channel=channel, network=irc.network):
                        f = self._logChan
                    i.submark(irc, channel, mode, mask, reason, irc.prefix,
                        self.getDb(irc.network), f, self)
            else:
                # increase duration, until the wrong action stopped
                f = None
                if self.registryValue('announceBotEdit', channel=channel, network=irc.network):
                    f = self._logChan
                chan = self.getChan(irc, channel)
                item = chan.getItem(mode, mask)
                oldDuration = int(item.expire-item.when)
                i.edit(irc, channel, mode, mask, int(oldDuration+duration), irc.prefix,
                    self.getDb(irc.network), self._schedule, f, self)
                if reason and len(reason):
                    f = None
                    if self.registryValue('announceBotMark', channel=channel, network=irc.network):
                        f = self._logChan
                    i.mark(irc, item.uid, reason, irc.prefix,
                        self.getDb(irc.network), f, self)
            self.forceTickle = True
            self._tickle(irc)
        else:
            results = []
            i = self.getIrc(irc)
            for nick in list(irc.state.channels[channel].users):
                if nick in i.nicks and nick != irc.nick:
                    n = self.getNick(irc, nick)
                    m = match(mask, n, irc, self.registryValue('resolveIp'))
                    if m:
                        results.append(nick)
            if len(results) and mode in 'kr':
                chan = self.getChan(irc, channel)
                if not (reason and len(reason)):
                    reason = random.choice(self.registryValue('kickMessage', channel=channel, network=irc.network))
                for n in results:
                    if mode == 'k':
                        chan.action.enqueue(ircmsgs.IrcMsg('KICK %s %s :%s' % (channel, n, reason)))
                        self.forceTickle = True
                    elif mode == 'r':
                        chan.action.enqueue(ircmsgs.IrcMsg('REMOVE %s %s :%s' % (channel, n, reason)))
                        self.forceTickle = True
                self._tickle(irc)
            else:
                log.error('%s %s %s %s %s unsupported mode' % (channel, mode, mask, duration, reason))

    def _isSomething(self, irc, channel, key, prop):
        if not self.registryValue('enabled', channel=channel, network=irc.network):
            return False
        chan = self.getChan(irc, channel)
        if prop == 'massJoin' or prop == 'cycle':
            if chan.netsplit:
                return False
        limit = self.registryValue('%sPermit' % prop, channel=channel, network=irc.network)
        if limit < 0:
            return False
        flag = ircdb.makeChannelCapability(channel, prop)
        if not ircdb.checkCapability(key, flag):
            return False
        chan = self.getChan(irc, channel)
        life = self.registryValue('%sLife' % prop, channel=channel, network=irc.network)
        if prop not in chan.spam:
            chan.spam[prop] = {}
        if key not in chan.spam[prop] or chan.spam[prop][key].timeout != life:
            chan.spam[prop][key] = utils.structures.TimeoutQueue(life)
        chan.spam[prop][key].enqueue(key)
        if len(chan.spam[prop][key]) > limit:
            log.info('[%s] %s is detected as %s' % (channel, key, prop))
            chan.spam[prop][key].reset()
            return True
        return False

    def _isBad(self, irc, channel, key):
        b = self._isSomething(irc, channel, key, 'bad')
        if b:
            chan = self.getChan(irc, channel)
            if self._isSomething(irc, channel, channel, 'attack') and not chan.attacked:
                # if number of bad users raise the allowed limit, bot has to set channel attackmode
                # TODO: retrieve all wrong users and find the best pattern to use against them
                chan.attacked = True
                if self.registryValue('attackMode', channel=channel, network=irc.network) == 'd':
                    if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                        self._logChan(irc, channel, '[%s] attackMode applied' % ircutils.bold(channel))
                    else:
                        self._logChan(irc, channel, '[%s] attackMode applied' % channel)
                else:
                    chan.action.enqueue(ircmsgs.mode(channel,
                        args=(self.registryValue('attackMode', channel=channel, network=irc.network),)))
                def unAttack():
                    if channel in list(irc.state.channels.keys()):
                        if self.registryValue('attackUnMode', channel=channel, network=irc.network) == 'd':
                            if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                                self._logChan(irc, channel, '[%s] attackUnMode applied' % ircutils.bold(channel))
                            else:
                                self._logChan(irc, channel, '[%s] attackUnMode applied' % channel)
                        else:
                            chan.action.enqueue(ircmsgs.mode(channel,
                                args=(self.registryValue('attackUnMode', channel=channel, network=irc.network),)))
                        chan.attacked = False
                schedule.addEvent(unAttack, time.time()
                    + self.registryValue('attackDuration', channel=channel, network=irc.network))
        return b

    def _isHilight(self, irc, channel, key, message):
        if not self.registryValue('enabled', channel=channel, network=irc.network):
            return False
        limit = self.registryValue('hilightPermit', channel=channel, network=irc.network)
        if limit < 0:
            return False
        count = 0
        users = []
        msg = message.lower()
        for user in list(irc.state.channels[channel].users):
            if len(user) > 2:
                users.append(user.lower())
        for user in users:
            if user in msg:
                count += 1
        return count > limit

    def _addTemporaryPattern(self, irc, channel, pattern, level, force, doNotLoop):
        patternLength = self.registryValue('repeatPatternMinimum', channel=channel, network=irc.network)
        if patternLength < 0 and not force:
            return
        if len(pattern) < patternLength and not force:
            return
        log.info('%s adding pattern %s' % (level, pattern))
        life = self.registryValue('repeatPatternLife', channel=channel, network=irc.network)
        key = 'pattern%s' % channel
        chan = self.getChan(irc, channel)
        if key not in chan.repeatLogs or chan.repeatLogs[key].timeout != life:
            chan.repeatLogs[key] = utils.structures.TimeoutQueue(life)
        if self.registryValue('announceRepeatPattern', channel=channel, network=irc.network):
            if self.registryValue('useColorForAnnounces', channel=channel, network=irc.network):
                self._logChan(irc, channel, '[%s] pattern created "%s" (%s)' % (
                    ircutils.bold(channel), ircutils.mircColor(pattern, 'red'), level))
            else:
                self._logChan(irc, channel, '[%s] pattern created "%s" (%s)' % (
                    channel, pattern, level))
        chan.repeatLogs[key].enqueue(pattern)
        if doNotLoop:
            return
        patternID = self.registryValue('shareComputedPatternID', channel=channel, network=irc.network)
        if patternID < 0:
            return
        for c in irc.state.channels:
            if irc.isChannel(c) and not channel == c:
                if patternID == self.registryValue('shareComputedPatternID', channel=c, network=irc.network):
                    self._addTemporaryPattern(
                        irc, c, pattern, level, force, doNotLoop)

    def _computePattern(self, message, logs, probability, patternLength):
        candidate = None
        bad = False
        for msg in logs:
            if compareString(message, msg) >= probability:
                bad = True
                if patternLength > -1:
                    found = largestString(message, msg)
                    if found and len(found) > patternLength:
                        if candidate:
                            if len(candidate) < len(found):
                                candidate = found
                        else:
                            candidate = found
        return (bad, candidate)

    def _isRepeat(self, irc, channel, key, message):
        if not self.registryValue('enabled', channel=channel, network=irc.network):
            return False
        if self.registryValue('repeatPermit', channel=channel, network=irc.network) < 0:
            return False
        chan = self.getChan(irc, channel)
        timeout = self.registryValue('repeatLife', channel=channel, network=irc.network)
        if key not in chan.repeatLogs or chan.repeatLogs[key].timeout != timeout:
            chan.repeatLogs[key] = utils.structures.TimeoutQueue(timeout)
        count = self.registryValue('repeatCount', channel=channel, network=irc.network)
        probability = self.registryValue('repeatPercent', channel=channel, network=irc.network)
        minimum = self.registryValue('repeatMinimum', channel=channel, network=irc.network)
        pattern = findPattern(message, count, minimum, probability)
        if pattern:
            self._addTemporaryPattern(irc, channel, pattern, 'single msg', False, False)
            if self._isSomething(irc, channel, key, 'repeat'):
                return True
        patternLength = self.registryValue('repeatPatternMinimum', channel=channel, network=irc.network)
        logs = chan.repeatLogs[key]
        (flag, pattern) = self._computePattern(message, logs, probability, patternLength)
        result = False
        if flag:
            result = self._isSomething(irc, channel, key, 'repeat')
        chan.repeatLogs[key].enqueue(message)
        if result:
            if pattern:
                self._addTemporaryPattern(irc, channel, pattern, 'single src', False, False)
        return result
        if channel not in chan.repeatLogs or chan.repeatLogs[channel].timeout != timeout:
            chan.repeatLogs[channel] = utils.structures.TimeoutQueue(timeout)
        logs = chan.repeatLogs[channel]
        (flag, pattern) = self._computePattern(message, logs, probability, patternLength)
        chan.repeatLogs[channel].enqueue(message)
        result = False
        if flag:
            result = self._isSomething(irc, channel, channel, 'repeat')
            if result:
                if pattern:
                    self._addTemporaryPattern(irc, channel, pattern, 'all src', False, False)
        return result

    def _isCap(self, irc, channel, key, message):
        if not self.registryValue('enabled', channel=channel, network=irc.network):
            return False
        if self.registryValue('capPermit', channel=channel, network=irc.network) < 0:
            return False
        trigger = self.registryValue('capPercent', channel=channel, network=irc.network)
        match = self.recaps.findall(message)
        if len(match) and len(message):
            percent = len(match) / len(message)
            if percent >= trigger:
                return self._isSomething(irc, channel, key, 'cap')
        return False

    def die(self):
        try:
            schedule.removeEvent('ChanTracker')
        except:
            pass


Class = ChanTracker
