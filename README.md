# ChanTracker — a Supybot plugin for ban tracking #

This Supybot plugin keeps records of channel mode changes in an SQLite database and permits
management of them over time. It stores affected users, enabling deep searching through them,
reviewing actives, editing duration, showing logs, marking/annotating them, etc.

The plugin is used in various and large channels on Libera.Chat and other networks.
This version works with Python 3.

## Installation ##

Note that you may need a newer version of Limnoria than your distribution provides, so you may
need to install it from the source code or via PyPI/`pip` to make the plugin function.
(Currently it requires Limnoria version 2018.04.14 or newer.)

You can install the plugin with:

    pip3 install git+https://github.com/ncoevoet/ChanTracker.git

Or with Limnoria versions older than 2020.05.08, in your bot's `plugins` directory:

    git clone https://github.com/ncoevoet/ChanTracker.git

Then `@load ChanTracker`.

## Commands ##

    @b,e,i,q [<channel>] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1> or empty means forever] <reason>) -- +mode targets for duration <reason> is mandatory
    @ub,ue,ui,uq [<channel>] <nick|hostmask|*> [<nick|hostmask>]) -- sets -mode on them, if * found, remove them all
    @check [<channel>] <pattern> returns list of users who will be affected by such pattern
    @edit <id>[,<id>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1>] means forever) -- change expiration of some active modes
    @info <id> returns information about a mode change
    @affect <id> returns affected users by a mode placed
    @mark <id>[,<id>] <message> add a comment about a mode change
    @editandmark <id>[,<id>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1>] [<comment>] edit duration and add comment on a mode change
    @pending [<channel>] (pending [--mode=<e|b|q|l>] [--oper=<nick|hostmask>] [--never] [<channel>] ) -- returns active items for --mode if given, filtered by --oper if given, --never never expire only if given
    @query [--deep] [--never] [--active] [--channel=<channel>] <pattern|hostmask|comment>) -- search inside ban database, --deep to search on log, --never returns items set forever and active, --active returns only active modes, --channel reduces results to a specific channel
    @match [<channel>] <nick|hostmask> returns list of modes that affects the nick,hostmask given
    @detail <id> returns log from a mode change
    @r [<channel>] <nick> [<reason>] do a force part on <nick> in <channel> with <reason> if provided
    @modes [<channel>] <mode> Sets the mode in <channel> to <mode>, sending the arguments given, bot will ask for op if needed.
    @summary [<channel>] returns some stats about <channel>
    @addpattern [<channel>] <limit> <life> <mode>(qbeId) [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] <pattern>) add a <pattern> which triggers <mode> for <duration> if the <pattern> appears more than <limit> (0 for immediate action) during <life> in seconds
    @addregexpattern [<channel>] <limit> <life> <mode>(qbeId) [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] /<pattern>/) add a <pattern> which triggers <mode> for <duration> if the <pattern> appears more than <limit> (0 for immediate action) during <life> in seconds
    @rmpattern [<channel>] <id>[,<id>] remove patterns
    @lspattern [<channel>] [<id|pattern>] return patterns in <channel> filtered by optional <pattern> or <id>
    @addtmp [<channel>] <pattern> add temporary pattern which follows repeat punishments
    @rmtmp [<channel>] remove temporary patterns if any

    @cflood [<channel>] [<permit>] [<life>] [<mode>] [<duration>] return channel's config or apply <mode> (bqeIkrdD) for <duration> (in seconds) if a user sends more than <permit> (-1 to disable) messages during <life> (in seconds)
    @crepeat [<channel>] [<permit>] [<life>] [<mode>] [<duration>] [<minimum>] [<probability>] [<count>] [<patternLength>] [<patternLife>] return channel's config or apply <mode> (bqeIkrdD) for <duration> (in seconds) if <permit> (-1 to disable) repetitions are found during <life> (in seconds); it will create a temporary lethal pattern with a mininum of <patternLength> (-1 to disable pattern creation); <probablity> is a float between 0 and 1
    @chl [<channel>] [<permit>] [<mode>] [<duration>] return channel's config or apply <mode> (bqeIkrdD) during <duration> (in seconds) if <permit> (-1 to disable) channel nicks are found in a message
    @cnotice [<channel>] [<permit>] [<life>] [<mode>] [<duration>] return channel's config or apply <mode> (bqeIkrdD) for <duration> (in seconds) if <permit> (-1 to disable) messages are channel notices during <life> (in seconds)
    @ccycle [<channel>] [<permit>] [<life>] [<mode>] [<duration>] return channel's config or apply <mode> (bqeIkrdD) for <duration> (in seconds) if <permit> (-1 to disable) parts/quits are received by a host during <life> (in seconds)
    @cclone [<channel>] [<permit>] [<mode>] [<duration>] return channel's config or apply <mode> (bqeIkrdD) for <duration> (in seconds) if <permit> (-1 to disable) users with the same host join the channel
    @cnick [<channel>] [<permit>] [<life>] [<mode>] [<duration>] return channel's config or apply <mode> (bqeIkrdD) during <duration> (in seconds) if a user changes nick <permit> (-1 to disable) times during <life> (in seconds)
    @ccap [<channel>] [<permit>] [<life>] [<mode>] [<duration>] [<probability>] return channel's config or apply <mode> (bqeIkrdD) for <duration> (in seconds) if <permit> (-1 to disable) messages during <life> (in seconds) contain more than <probability> (float between 0-1) uppercase chars
    @cbad [<channel>] [<permit>] [<life>] [<mode>] [<duration>] return channel's config or apply <mode> (bqeIkrdD) for <duration> (in seconds) if a user triggers <permit> (-1 to disable) channel protections during <life> (in seconds)
    @cautoexpire [<channel>] [<autoexpire>] return channel's config or auto remove new elements after <autoexpire> (-1 to disable, in seconds)

## General Usage ##

The bot can be used to place and remove bans (rather than the op setting channel modes directly).
For example, to quiet the argumentative user 'ian' for 10 minutes and ban the spammer 'ham' for a month:

    @q ian 10m argumentative again
    @b ham 30d silly spammer
    @b foo 1h30m must stop

These can also be done via a private message to the bot, although you must include the channel in the message:

    /msg mybigbadbot q #myChannel ian 10m argumentative again
    /msg mybigbadbot b #myChannel ham 30d silly spammer

For each of these bans, the nick is used to generate a `*!*@host` ban. The desired mask can be given directly
to the bot instead of the nick. Also note that, by default, the bot will also kick users that have a ban set
against them (details below).

Alternatively, the bot can be used to just track the mode changes, with ops using the capabilities of their
own IRC clients to set bans. The same sequence as before:

    /msg chanserv #myChannel op
    /mode #myChannel +q *!*@ranty.ian.home
    /msg mybigbadbot 10m argumentative again
    /mode #myChannel +b *!*@ham.spam
    /kick ham
    /msg mybigbadbot 30d silly spammer

If you annotate the bans within 5 minutes of setting them, then you can do so without any additional syntax as above.
Otherwise, the `pending`, `edit`, `mark`, and `editandmark` commands can be used to provide annotations and expiration
information. For example, if you had not immediately annotated the quiet:

    /msg mybigbadbot query ian!*@*
    /msg mybigbadbot pending #myChannel
    <mybigbadbot> [#18 +q ian!*@* by me!~me@example.net on 2014-04-13 13:28:16 GMT]
    /msg bigbadbot edit 18 20m
    /msg bigbadbot mark 18 even more argumentative and EXTREMELY ANGRY
    /msg bigbadbot editandmark 18 20m even more argumentative and EXTREMELY ANGRY

ChanTracker also allows you to work out which users would be affected by a ban before it is placed and which bans affect
a given user (assuming the bot shares a channel with the user).

    /msg bigbadbot check #myChannel *!*@*.com     <-- oops?
    /msg bigbadbot match #myChannel ian           <-- will return
    <bigbadbot> [#21 +b ian!*@* by me!~me@example.net expires at 2014-04-13 15:20:03 GMT] "even angrier"

## Settings ##

If you want the bot to manage its own op status, you must change this setting:

    @config supybot.plugins.ChanTracker.doNothingAboutOwnOpStatus False
    @config channel #myChannel supybot.plugins.ChanTracker.doNothingAboutOwnOpStatus True

After `doNothingAboutOwnOpStatus` is changed to `False`, the bot will deop in each channel it is opped in, so take a look at:

    @config supybot.plugins.ChanTracker.keepOp False
    @config channel #myChannel supybot.plugins.ChanTracker.keepOp True

You should decrease the ping interval, because when the bot requests a load of data when it joins a channel,
sometimes it could be throttled by the server, and the bot will retry at next ping/pong:

    @config supybot.protocols.irc.ping.interval 60

Here is the list of data requested by the bot at join:

    JOIN :#channel
    MODE :#channel
    MODE :#channel b
    MODE :#channel q
    WHO #CHANNEL %tuhnairf,1

...and if opped or at first op:

    MODE :#channel e
    MODE :#channel I

The channel modes that will be tracked are currently defined here (by default `bq`, and `eI` if opped
-- only ops can see the `e` and `I` lists for a channel):

    @config supybot.plugins.ChanTracker.modesToAsk
    @config supybot.plugins.ChanTracker.modesToAskWhenOpped
    @config channel #myChannel supybot.plugins.ChanTracker.modesToAsk b, q
    @config channel #myChannel supybot.plugins.ChanTracker.modesToAskWhenOpped e

The command used by the bot to op itself is editable here, where `$channel` and `$nick` will be replaced
with the target channel and the bot's nick at runtime:

    @config supybot.plugins.ChanTracker.opCommand "PRIVMSG ChanServ :OP $channel $nick"

You can also tell the bot to use ChanServ for quiet and unquiet, if it has the `+r` flag on Atheme services:

    @config supybot.plugins.ChanTracker.useChanServForQuiets True
    @config supybot.plugins.ChanTracker.quietCommand "PRIVMSG ChanServ :QUIET $channel $hostmask"
    @config supybot.plugins.ChanTracker.unquietCommand "PRIVMSG ChanServ :UNQUIET $channel $hostmask"

For more readable date information in output, you should change this:

    @config supybot.reply.format.time.elapsed.short True

The bot can have a *reporting channel* like an -ops channel, where it forwards a lot of important
information about channel activity. You can set it globally or per channel:

    @config supybot.plugins.ChanTracker.logChannel #myGeneralSecretChannel
    @config channel #myChannel supybot.plugins.ChanTracker.logChannel #myChannel-ops

You can use colors in it:

    @config channel #myChannel supybot.plugins.ChanTracker.useColorForAnnounces True

You can tweak which information you would like to be forwarded to the reporting channel.
Some reporting is activated by default, like topic changes, mode changes, etc.
While some are not, like ban/quiet and edit/mark by the bot, etc. Take a look at:

    @search supybot.plugins.ChanTracker.announce
    @config help supybot.plugins.ChanTracker.announceModes

If desired, the bot can send a private message to the op that sets a tracked mode. Note the op must
be known as channel op by the bot; the bot owner automatically has that capability:

    @config channel #myChannel supybot.plugins.ChanTracker.askOpAboutMode True

You can add op capability to someone by doing:

    @user register opaccount password
    @hostmask add opaccount *!*@something
    @admin capability add opaccount #myChannel,op

The bot can set a default duration for new tracked mode changes, in order to automatically remove them:

    @config channel #myChannel supybot.plugins.ChanTracker.autoExpire 3600 (1 hour)

The plugin can create persistent bans to help manage large ban lists that exceed the IRCd's limits on
the length of ban lists. It can remove bans from the IRCd ban list while checking all joining users
against its own lists. If a user matches, then the IRCd ban is reinstated:

    @config channel #myChannel supybot.plugins.ChanTracker.useChannelBansForPermanentBan true
    @channel ban add #myChannel *!*@mask
    @b #example --perm baduser,baduser2 1w stop trolling (--perm adds computed hostmasks to Channel.ban)

With `autoExpire` enabled, the IRCd list is pruned as appropriate and bans are rotated in a way to not reveal
the pattern used for the match. Due to a Supybot limitation, extended bans are not supported with this feature.

If supported by the IRCd, the bot can track account changes and get GECOS and username information when a user
joins the channel. This requires IRCd CAP features: https://ircv3.net/specs/extensions/capability-negotiation.html

The plugin also supports extended bans/quiets including `$a`, `$r`, `$x`, and `$j` (account name, real name, full match,
and ban channel). If you want the plugin to support your IRCd's extended bans, please file a feature request or contact
us via our IRC channel.

By default, if the bot is asked to set a ban (`+b`), it will also kick affected users. See:

    @config supybot.plugins.ChanTracker.kickMode
    @config supybot.plugins.ChanTracker.kickMessage
    @config help supybot.plugins.ChanTracker.kickOnMode

The bot will remove exemption modes (that is exempt `e`, or invite exempt `I`) for people banned if
`doActionAgainstAffected` for the given channel is `True`.

## Channel Protection ##

The plugin has a lot of built-in channel protection features that can be enabled either
individually and per-channel, or globally:

- flood detection
- low-rate flood detection: flooding but with client rate-limiting
- repeat detection
- capslock: detect people who are EXTREMELY ANGRY
- ctcp: detect sending CTCPs to the channel
- notices: detect sending notices to the channel
- hilight: nick spam
- nick: nick change spam
- cycle: join/part flood
- massJoin
- evades of quiet/bans via gateway (if `resolveIp` is enabled)
- clone detection

You should tweak settings to fit your needs, do not use default values. It really depends
on the channel's population and usage...

Each of those detections has the same kind of settings:

- `*Permit`: (-1 to disable)
- `*Life`: time interval over which the bot will track previous messages/behaviour
- `*Mode`: allows you to select which action you want to use against the user
- `*Duration`: duration of the action taken
- `*Comment`: (empty for no comment)

The action modes that can be set are:

- `q`: quiet the user
- `b`: ban the user
- `k`: kick the user
- `r`: remove (force-part) the user, if the IRCd has the feature
- `d`: debug -- forward action to log channel, if configured

For bans (`b` and `q` modes), you can choose the `*Duration` of the quiet/ban, and set a `*Comment` for it.
The `bad` settings, when enabled (`badPermit > -1`) keep track of users who did something wrong during `badLife`,
and can lead to `badMode` if the user exceeds the limit.

**Example:** Flood control -- to quiet for 1 minute anyone who sends more than 4 messages in 7 seconds to #channel;
if the user continues to flood, after 3 times within 5 minutes they will be banned:

    @config channel #channel supybot.plugins.ChanTracker.floodPermit 4 <-- max number of messages allowed
    @config channel #channel supybot.plugins.ChanTracker.floodLife 7 <-- in 7 seconds
    @config channel #channel supybot.plugins.ChanTracker.floodMode q <-- quiet the user
    @config channel #channel supybot.plugins.ChanTracker.floodDuration 60 <-- for 60 seconds
    @config channel #channel supybot.plugins.ChanTracker.badPermit 2 <-- if user does that 3 times (more than 2)
    @config channel #channel supybot.plugins.ChanTracker.badLife 300 <-- during 5 minutes
    @config channel #channel supybot.plugins.ChanTracker.badMode b <-- ban them

Additionally, the bot can track how many bad actions occur over a period of time and if a threshold is passed,
this constitutes an attack on the channel. The `attack*` settings, when enabled keep track of bad actions,
and if the number exceeds `attackPermit` within `attackLife`, some specified channel modes are set for `attackDuration`.

**Example:** Bot flooding -- catch a wave of bots which send the same message from different hosts:

    @config channel #channel supybot.plugins.ChanTracker.attackPermit 2 <-- if bot triggers 3 bad actions (more than 2)
    @config channel #channel supybot.plugins.ChanTracker.attackLife 300 <-- during 5 minutes
    @config channel #channel supybot.plugins.chantracker.attackMode +rq $~a <-- then bot will set these modes
    @config channel #channel supybot.plugins.chantracker.attackDuration 1800 <-- for 30 minutes
    @config channel #channel supybot.plugins.chantracker.attackUnMode -rq $~a <- and bot will set these modes after they passed

**Example:** A user repeating the same thing:

    @config channel #channel supybot.plugins.ChanTracker.repeatPermit 3 <-- triggered after 3 similar messages
    @config channel #channel supybot.plugins.ChanTracker.repeatLife 40 <-- keep previous messages during 40 seconds

    @config channel #channel supybot.plugins.ChanTracker.repeatMinimum 8 <-- minimum size of candidate patterns
    @config channel #channel supybot.plugins.ChanTracker.repeatPercent 0.88 <-- 1.00 for identical message, don't go too low or you will get false positives
    @config channel #channel supybot.plugins.ChanTracker.repeatCount 6 <-- or the number of times a pattern is repeated in a single message
    @config channel #channel supybot.plugins.ChanTracker.repeatPatternMinimum 12 <-- mininum size of temporary lethal pattern
    @config channel #channel supybot.plugins.ChanTracker.repeatPatternLife 120 <-- life duration of those patterns in seconds

    @config channel #channel supybot.plugins.ChanTracker.repeatMode q <-- quiet
    @config channel #channel supybot.plugins.ChanTracker.repeatDuration 3600 <-- for 1 hour

## `protected` Capability ##

You must remove the `protected` capability given by default to everyone, because the bot will not do anything
against users having this capability:

    @defaultcapability remove protected

## Other Tips ##

Maintaining separate bots for the banning/bantracking functions and other factoid, snarfing,
or amusement functions is good practice.

If the main purpose of your bot is to manage bans etc and never interact with users, you should remove all plugins
from the default capabilities, which will prevent the bot from responding to various commands and being used as a
flood tool by others (like with `@echo SPAM`):

    @defaultcapability remove <pluginname>

You could otherwise change the value of `supybot.capabilities.default`, but be prepared to waste a lot of time
each time you add a new user account on your bot. If the setting is changed to `False`, then when you want to grant
access to a command for someone, you must do it this way:

    @admin capability add <accountname> User
    @admin capability add <accountname> User.whoami
    @admin capability add <accountname> whoami

If your bot manages different channels or communities, remove all `User.<action>` from the default capabilities,
create one user per channel/community, and add ops' hostmasks to it -- it's easier to manage this way.
Until you have someone with rights in multiple channels/communities, who will need a separate account.

You should keep your bot as quiet as possible. It should not reply to errors, users without capabilities, etc:

    @config supybot.reply.error.noCapability True
    @config supybot.replies.genericNoCapability ""
    @config supybot.abuse.flood.command.invalid.notify False
    @config supybot.reply.whenNotCommand False
    @config supybot.reply.error.detailed False
    @config supybot.replies.error ""
    @config defaultcapability remove channel.nicks
    @config defaultcapability remove channel.alert
    @config defaultcapability remove alias.add
    @config defaultcapability remove config
    @config defaultcapability remove help
    @config defaultcapability remove list

There are other commands that are prone to abuse as well. It's better to use this command:

    @config supybot.capabilities.default False

## Bugs and Features ##

Requests can be made via https://github.com/ncoevoet/ChanTracker
or in #chantracker on chat.libera.chat
