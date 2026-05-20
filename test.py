###
# Copyright (c) 2013, Nicolas Coevoet
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

from supybot.test import *

import time
import supybot.conf as conf

from . import plugin


class ListTrackerTestCase(PluginTestCase):
    # smoke test: confirms the plugin imports and loads cleanly
    plugins = ('ChanTracker',)


class _BanDbMixin:
    """Shared helpers for tests that exercise the ChanTracker ban database.

    The SQLite database file is created on first getDb() and persists across
    test methods in a single run, so each test must call _wipe() first.
    """

    def _cb(self):
        return self.irc.getCallback('ChanTracker')

    def _db(self):
        return self._cb().getDb(self.irc.network)

    def _wipe(self):
        db = self._db()
        c = db.cursor()
        for table in ('bans', 'nicks', 'comments'):
            c.execute('DELETE FROM %s' % table)
        db.commit()
        c.close()

    def _addBan(self, channel='#test', removed_at=None, mask='*!*@host'):
        # insert one ban row plus its nick + comment metadata; return the ban id
        db = self._db()
        c = db.cursor()
        now = time.time()
        c.execute("""INSERT INTO bans
                     (channel, oper, kind, mask, begin_at, end_at, removed_at, removed_by)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                  (channel, 'op!user@host', 'b', mask, now - 86400, now,
                   removed_at, None if removed_at is None else 'op!user@host'))
        uid = c.lastrowid
        c.execute("""INSERT INTO nicks (ban_id, ban, full, log) VALUES (?, ?, ?, ?)""",
                  (uid, mask, 'nick!user@host', 'message log'))
        c.execute("""INSERT INTO comments (ban_id, oper, at, comment) VALUES (?, ?, ?, ?)""",
                  (uid, 'op!user@host', now, 'a comment'))
        db.commit()
        c.close()
        return uid

    def _count(self, table, uid):
        db = self._db()
        c = db.cursor()
        column = 'id' if table == 'bans' else 'ban_id'
        c.execute('SELECT COUNT(*) FROM %s WHERE %s=?' % (table, column), (uid,))
        n = c.fetchone()[0]
        c.close()
        return n


class ChanTrackerRetentionTestCase(_BanDbMixin, PluginTestCase):
    """Behavioral tests for the GDPR ban-retention cleanup (issue #37).

    ChanTracker._retentionCleanup() permanently deletes bans removed from the
    channel, and their nicks/comments metadata, once older than the per-channel
    'banRetention' period (-1 disables, 0 purges on the next run).

    The tests drive _retentionCleanup() directly and assert the row-level
    outcome; they cover the stable contract (retention threshold, the
    nicks/comments cascade, the disable switch), not the once-per-day _tickle()
    scheduling guard.
    """
    plugins = ('ChanTracker',)

    def _setRetention(self, days, channel='#test'):
        conf.supybot.plugins.ChanTracker.banRetention.get(channel).setValue(days)

    def testRetentionDisabledKeepsEverything(self):
        self._wipe()
        old = self._addBan(removed_at=time.time() - 400 * 86400)
        self._setRetention(-1)
        self._cb()._retentionCleanup(self.irc)
        self.assertEqual(self._count('bans', old), 1,
                         'banRetention=-1 must never delete anything')
        self.assertEqual(self._count('nicks', old), 1)
        self.assertEqual(self._count('comments', old), 1)

    def testRetentionDeletesOldRemovedBanWithMetadata(self):
        self._wipe()
        old = self._addBan(removed_at=time.time() - 400 * 86400, mask='*!*@old')
        recent = self._addBan(removed_at=time.time() - 1 * 86400, mask='*!*@recent')
        self._setRetention(30)
        self._cb()._retentionCleanup(self.irc)
        # 400 days old, past the 30-day window -> ban and its metadata purged
        self.assertEqual(self._count('bans', old), 0)
        self.assertEqual(self._count('nicks', old), 0,
                         'nicks metadata must be deleted together with the ban')
        self.assertEqual(self._count('comments', old), 0,
                         'comments metadata must be deleted together with the ban')
        # 1 day old, inside the 30-day window -> kept
        self.assertEqual(self._count('bans', recent), 1)
        self.assertEqual(self._count('nicks', recent), 1)
        self.assertEqual(self._count('comments', recent), 1)

    def testRetentionNeverDeletesActiveBan(self):
        self._wipe()
        active = self._addBan(removed_at=None, mask='*!*@active')
        # a removed+old ban in the same channel ensures the channel is scanned
        removed = self._addBan(removed_at=time.time() - 400 * 86400, mask='*!*@gone')
        self._setRetention(0)
        self._cb()._retentionCleanup(self.irc)
        self.assertEqual(self._count('bans', removed), 0,
                         'a removed ban older than the window should be purged')
        self.assertEqual(self._count('bans', active), 1,
                         'a ban that was never removed must never be purged')

    def testRetentionZeroPurgesAlreadyRemovedBan(self):
        self._wipe()
        removed = self._addBan(removed_at=time.time() - 60, mask='*!*@gone')
        self._setRetention(0)
        self._cb()._retentionCleanup(self.irc)
        self.assertEqual(self._count('bans', removed), 0,
                         'banRetention=0 must purge already-removed bans')

    def testRetentionCleanupWithNothingRemovedIsHarmless(self):
        self._wipe()
        active = self._addBan(removed_at=None)
        self._setRetention(7)
        # must run without error even when there is nothing removed to scan
        self._cb()._retentionCleanup(self.irc)
        self.assertEqual(self._count('bans', active), 1)


class ChanTrackerIrcdTestCase(_BanDbMixin, PluginTestCase):
    """Tests for Ircd.remove() -- the single-row deletion primitive used by the
    ban-removal commands. It must delete the ban and cascade to its metadata."""
    plugins = ('ChanTracker',)

    def testIrcdRemoveDeletesBanAndCascadesMetadata(self):
        self._wipe()
        uid = self._addBan()
        ircd = self._cb().getIrc(self.irc)
        self.assertTrue(ircd.remove(uid, self._db()),
                        'remove() must return True when the ban exists')
        self.assertEqual(self._count('bans', uid), 0)
        self.assertEqual(self._count('nicks', uid), 0,
                         'remove() must cascade to the nicks table')
        self.assertEqual(self._count('comments', uid), 0,
                         'remove() must cascade to the comments table')

    def testIrcdRemoveMissingIdReturnsFalse(self):
        self._wipe()
        ircd = self._cb().getIrc(self.irc)
        self.assertFalse(ircd.remove(999999, self._db()),
                         'remove() must return False for an unknown id')


class ChanTrackerHelpersTestCase(PluginTestCase):
    """Tests for the pure text-analysis and formatting helpers that back the
    repeat/flood protections and the ban-history display."""
    plugins = ('ChanTracker',)

    def testCompareString(self):
        # Jaccard similarity over the two strings' character sets, 0..1
        self.assertEqual(plugin.compareString('hello', 'hello'), 1)
        self.assertEqual(plugin.compareString('abc', 'xyz'), 0)
        # {a,b,c,d} vs {a,b,c,e}: intersection 3, union 5 -> 0.6
        self.assertAlmostEqual(plugin.compareString('abcd', 'abce'), 0.6)

    def testRepetitions(self):
        self.assertEqual(list(plugin.repetitions('abcabc')), [('abc', 2)])
        self.assertEqual(list(plugin.repetitions('aaaa')), [('a', 4)])
        self.assertEqual(list(plugin.repetitions('abcdef')), [])

    def testLargestString(self):
        self.assertEqual(plugin.largestString('abcdefg', 'xxcdefyy'), 'cdef')
        self.assertEqual(plugin.largestString('hello', 'hello'), 'hello')
        self.assertEqual(plugin.largestString('abc', 'xyz'), '')

    def testFindPattern(self):
        # repeated >minimalLength pattern, count over minimalCount
        self.assertEqual(plugin.findPattern('spamspamspam', 2, 3, 0.5), 'spam')
        # count below minimalCount but percent over minimalPercent
        self.assertEqual(plugin.findPattern('abab', 5, 1, 0.9), 'ab')
        # nothing repeats -> None
        self.assertIsNone(plugin.findPattern('abcdxyz', 2, 3, 0.9))

    def testFloatToGMT(self):
        self.assertEqual(plugin.floatToGMT(0), '1970-01-01 00:00:00 GMT')
        self.assertEqual(plugin.floatToGMT(1000000000), '2001-09-09 01:46:40 GMT')
        # non-numeric input is swallowed and returns None
        self.assertIsNone(plugin.floatToGMT('not-a-number'))

    def testGetDuration(self):
        self.assertIsNone(plugin.getDuration([]))
        self.assertEqual(plugin.getDuration([60, 30, 10]), 100)
        self.assertEqual(plugin.getDuration([3600]), 3600)

    def testClearExtendedBanPattern(self):
        # extban support is read from irc.state.supported (prefix,modes)
        self.irc.state.supported['extban'] = '$,ajrxz'
        self.assertEqual(
            plugin.clearExtendedBanPattern('$a:SomeAccount', self.irc), 'SomeAccount')
        self.assertEqual(
            plugin.clearExtendedBanPattern('$~a:SomeAccount', self.irc), 'SomeAccount')
        # a plain hostmask is returned unchanged
        self.assertEqual(
            plugin.clearExtendedBanPattern('*!*@host.example.com', self.irc),
            '*!*@host.example.com')


class ChanTrackerStateTestCase(PluginTestCase):
    """Tests for the in-memory state classes (Nick, Pattern) and the hostmask
    computation used to pick a ban mask for a user."""
    plugins = ('ChanTracker',)

    def testNickSetIp(self):
        self.assertEqual(plugin.Nick(5).setIp('192.0.2.10').ip, '192.0.2.10')
        # 255.255.255.255 is explicitly rejected (placeholder address)
        self.assertIsNone(plugin.Nick(5).setIp('255.255.255.255').ip)
        # a non-IP string is rejected
        self.assertIsNone(plugin.Nick(5).setIp('not-an-ip').ip)

    def testNickSetAccount(self):
        self.assertEqual(plugin.Nick(5).setAccount('alice').account, 'alice')
        # '*' means "no account"
        self.assertIsNone(plugin.Nick(5).setAccount('*').account)

    def testNickSetPrefixResetsIp(self):
        n = plugin.Nick(5)
        n.setPrefix('bob!user@host').setIp('192.0.2.1')
        n.setPrefix('bob!user@other')
        self.assertIsNone(n.ip, 'changing the prefix must drop the cached ip')
        n.setIp('192.0.2.1')
        n.setPrefix('bob!user@other')
        self.assertEqual(n.ip, '192.0.2.1',
                         'setting the same prefix must keep the cached ip')

    def testNickAddLogIsBounded(self):
        n = plugin.Nick(2)
        n.addLog('#chan', 'first')
        n.addLog('#chan', 'second')
        n.addLog('#chan', 'third')
        self.assertEqual(len(n.logs), 2, 'the log must not grow past logSize')
        # oldest entry dropped; each entry is [timestamp, target, message]
        self.assertEqual([entry[2] for entry in n.logs], ['second', 'third'])

    def testPatternPlainMatch(self):
        p = plugin.Pattern(1, 'badword', False, 3, 60, 'b', 0)
        self.assertEqual(p.match('this has a badword in it'), (True, 'badword'))
        self.assertEqual(p.match('this is clean'), (False, None))

    def testPatternRegexpMatch(self):
        p = plugin.Pattern(2, 'm/ab+c/', True, 3, 60, 'b', 0)
        self.assertEqual(p.match('zz abbbc zz'), (True, 'abbbc'))
        self.assertEqual(p.match('no match here'), (False, None))

    def testGetBestPattern(self):
        n = plugin.Nick(5)
        n.setPrefix('bob!ident@host.example.com').setIp('192.0.2.5')
        self.assertEqual(plugin.getBestPattern(n, self.irc),
                         ['*!ident@192.0.2.5', '*!ident@host.example.com'])

    def testGetBestPatternCloakMasksIdent(self):
        # a user/ cloak (and a ~ident) collapse the ident part to '*'
        n = plugin.Nick(5)
        n.setPrefix('bob!~user@user/bob')
        self.assertEqual(plugin.getBestPattern(n, self.irc), ['*!*@user/bob'])

    def testGetBestPatternNoPrefixReturnsEmpty(self):
        self.assertEqual(plugin.getBestPattern(plugin.Nick(5), self.irc), [])
