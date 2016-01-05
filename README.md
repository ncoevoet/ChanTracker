# ChanTracker : a supybot plugin for ban tracking #

This supybot plugin keeps records of channel mode changes in a sqlite database and permits management of them over time. It stores affected users, enabling deep searching through them, reviewing actives, editing duration, showing logs, marking/annotating them, etc.

The plugin is used in various and large channels on freenode and others networks

For cidr supports, you must install ipaddress ( pip for python 2.7 https://pypi.python.org/pypi/py2-ipaddress ) or netaddr ( python 2.7 https://pypi.python.org/pypi/netaddr )

## Commands ##

    !b,e,i,q [<channel>] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1> or empty means forever] <reason>) -- +mode targets for duration <reason> is mandatory
    !ub,ue,ui,uq [<channel>] <nick|hostmask|*> [<nick|hostmask>]) -- sets -mode on them, if * found, remove them all
    !check [<channel>] <pattern> returns list of users who will be affected by such pattern
    !edit <id> [,<id>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1>] means forever) -- change expiration of some active modes
    !info <id> returns information about a mode change
    !affect <id> returns affected users by a mode placed
    !mark <id> [,<id>] <message> add a comment about a mode change
    !editandmark <id> [,<id>] [,<id>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1>] [<comment>] edit duration and add comment on a mode change
    !pending [<channel>] (pending [--mode=<e|b|q|l>] [--oper=<nick|hostmask>] [--never] [<channel>] ) -- returns active items for --mode if given, filtered by --oper if given, --never never expire only if given
    !query [--deep] [--never] [--active] [--channel=<channel>] <pattern|hostmask|comment>) -- search inside ban database, --deep to search on log, --never returns items set forever and active, --active returns only active modes, --channel reduces results to a specific channel
    !match [<channel>] <nick|hostmask> returns list of modes that affects the nick,hostmask given
    !detail <id> returns log from a mode change
    !remove [<channel>] <nick> [<reason>] do a force part on <nick> in <channel> with <reason> if provided
    !modes [<channel>] <mode> Sets the mode in <channel> to <mode>, sending the arguments given, bot will ask for op if needed.
    !summary [<channel>] returns some stats about <channel>

## General Usage ##

The bot can be used to place and remove bans (rather than the the op setting channel modes directly). For example, to quiet the argumentative user 'ian' for 10 minutes and ban the spammer 'ham' for a month:

    !q ian 10m argumentative again
    !b ham 30d silly spammer
    !b foo 1h30m must stop

These can also be done via a private message to the bot, although you must include the channel in the message:

    /msg mybigbadbot q #myChannel ian 10m argumentative again
    /msg mybigbadbot b #myChannel ham 30d silly spammer

For each of these bans, the nick is used to generate a \*!\*@host ban. The desired mask can be given directly to the bot instead of the nick. Also note that, by default, the bot will also kick users that have a +b set against them (details below).

Alternatively, the bot can be used just to track the mode changes, with ops using the capabilities of their own IRC clients to set bans. The same sequence as before:

    /msg chanserv #myChannel op
    /mode #myChannel +q *!*@ranty.ian.home
    /msg mybigbadbot 10m argumentative again
    /mode #myChannel +b *!*@ham.spam
    /kick ham
    /msg mybigbadbot 30d silly spammer

If you annotate the bans within 3 minutes of setting them, then you can do so without any additional syntax as above; if you miss that window or are otherwise not setting bans via the bot, the `pending`, `edit`, `mark` and `editandmark` commands can be used to provide annotations and expiration information. For example, if you had not immediately annotated the quiet.

    /msg mybigbadbot query ian!*@*
    /msg mybigbadbot pending #myChannel
    <mybigbadbot> [#18 +q ian!*@* by me!~me@example.net on 2014-04-13 13:28:16 GMT]
    /msg bigbadbot edit 18 20m
    /msg bigbadbot mark 18 even more argumentative and EXTREMELY ANGRY
    /msg bigbadbot editandmark 18 20m even more argumentative and EXTREMELY ANGRY

ChanTracker also allows you to work out which users would be affected by a ban before it is placed and which bans affect a given user ( assuming the bot shares a channel with the user ).

    /msg bigbadbot check #myChannel *!*@*.com     <-- oops?
    /msg bigbadbot match #myChannel ian           <-- will return 
    <bigbadbot> [#21 +b ian!*@* by me!~me@example.net expires at 2014-04-13 15:20:03 GMT] "even angrier"

## Settings ##

**If you want the bot to manage its own op status, you must change the config value**:

    !config supybot.plugins.ChanTracker.doNothingAboutOwnOpStatus False
    !config channel #myChannel supybot.plugins.ChanTracker.doNothingAboutOwnOpStatus True

After the 'doNothingAboutOwnOpStatus' changed to False, bot will deop in each channel is in (if opped) so take a look at:

    !config supybot.plugins.ChanTracker.keepOp False
    !config channel #myChannel supybot.plugins.ChanTracker.keepOp True

You should increase the ping interval because when the bot joins a channel it requests lots of data and sometimes the server takes time to answer

    !config supybot.protocols.irc.ping.interval 3600

Here list of data requested by the bot at join:

    JOIN :#channel
    MODE :#channel
    MODE :#channel b
    MODE :#channel q
    WHO #CHANNEL %tnuhiar,42

and if opped or at first op:

    MODE :#channel e
    MODE :#channel I

The channel modes that will be tracked are currently defined here (qb, and eI if opped -- only ops can see the e and I lists for a channel):

    !config supybot.plugins.ChanTracker.modesToAsk
    !config supybot.plugins.ChanTracker.modesToAskWhenOpped
    !config channel #myChannel supybot.plugins.ChanTracker.modesToAsk b, q
    !config channel #myChannel supybot.plugins.ChanTracker.modesToAskWhenOpped e

The command used by the bot to op itself is editable here:

    !config supybot.plugins.ChanTracker.opCommand by default it's "CS OP $channel $nick" 

Where $channel and $nick will be replaced by targeted channel and bot's nick at runtime, so you could replace it with :

    !config supybot.plugins.ChanTracker.opCommand "PRIVMSG ChanServ :OP $channel $nick"

You can also tell the bot to use ChanServ for quiet and unquiet, if it has +r flag, on freenode:

    !config supybot.plugins.ChanTracker.useChanServForQuiets True
    !config supybot.plugins.ChanTracker.quietCommand "PRIVMSG ChanServ :QUIET $channel $hostmask"
    !config supybot.plugins.ChanTracker.unquietCommand "PRIVMSG ChanServ :UNQUIET $channel $hostmask"

For more readable date information in output, you should change this:

    !config supybot.reply.format.time.elapsed.short True

The bot can have a "reporting channel" like an -ops channel, where it forwards a lot of important information about channel activity. You can set it globally or per channel:

    !config supybot.plugins.ChanTracker.logChannel #myGeneralSecretChannel
    !config channel #myChannel supybot.plugins.ChanTracker.logChannel #myChannel-ops

You can use colors in it:

    !config channel #myChannel supybot.plugins.ChanTracker.useColorForAnnounces True

You can tweak which information you would like to be forwarded to the reporting channel. Some reporting is activated by default like topic changes, mode changes, etc, some not, like bot's ban/quiet edit/mark etc. Take a look at:

    !search supybot.plugins.ChanTracker.announce
    !config help supybot.plugins.ChanTracker.announceModes

If desired, the bot can send a private message to the op that sets a tracked mode. Note the op must be known as channel's op by the bot; the bot owner automatically has that capability:

    !config channel #myChannel supybot.plugins.ChanTracker.askOpAboutMode True

You can add op capability to someone by doing:
    
    !user register opaccount password
    !hostmask add opaccount *!*@something
    !admin capability add opaccount #myChannel,op

The bot can set a default duration for new tracked mode changes, in order to auto remove them:

    !config channel #myChannel supybot.plugins.ChanTracker.autoExpire 3600 (1h)

The plugin can create persistent bans to help manage large ban lists that exceed the IRCd's limits on the length of ban lists. The plugin can remove bans from the IRCd ban list while checking all joining users against its own lists. If a user matches, then the IRCd ban is reinstated:

    !config channel #myChannel supybot.plugins.ChanTracker.useChannelBansForPermanentBan true
    !channel ban add #myChannel *!*@mask
    !b #example --perm baduser,baduser2  1w stop trolling ( --perm add computed hostmasks to Channel.ban )

With autoExpire enabled, the IRCd list is pruned as appropriate and bans are rotated in a way to not reveal the pattern used for the match. Due to a supybot limitation, extended bans are not supported with this feature.

If supported by the ircd, the bot can track account changes and get GECOS and username information when a user joins the channel. This requires ircd CAP features:  http://tools.ietf.org/html/draft-mitchell-irc-capabilities-01

The plugin also supports extended bans/quiets including $r, $x, $a, $j (real name, full match and account name, respectively). If you want the plugin to support your IRCd extended bans, please, report a bug or contact me directly.

By default, if the bot is asked to set a ban (+b), it will also kick affected users (Note: bot will only kick people if the ban was set by the bot -- if an op places the ban, the bot will not kick affected users). See:

    !config supybot.plugins.ChanTracker.kickMode
    !config supybot.plugins.ChanTracker.kickMessage
    !config help supybot.plugins.ChanTracker.kickOnMode
    
The bot will remove exception modes (that is exempt e, or invite exempt I) for people banned if 'doActionAgainstAffected' for given channel is True.

ChanTracker is trying to resolve ip behind host, but that can affect performance or freeze the bot due to socket's calls, if you use 'supybot.plugins.ChanTracker.resolveIp' to True, you should set 'supybot.debug.threadAllCommands' to True to avoid that. 

**Due to changes on January 5 2016**, if your bot has 'supybot.capabilities.default' to False, Bot must have an account on itself with his cloak/host inside and ChanTracker capability ( because it calls ChanTracker.resolve ).

    !user register botaccount randompassword
    !hostmask add botaccount *!ident@bot.host
    !admin capability add botaccount ChanTracker

## Channel Protection ##

The plugin has a lot of built-in channel protection features that can be enabled either individually and per channel, or globally:

- flood detection
- low-rate flood detection: flooding but with client rate-limiting
- repeat detection
- massRepeat detection: when same message comes from different users
- capslock: detect people who are EXTREMELY ANGRY
- ctcp: detect sending CTCP to the channel
- notices: detect sending notices to the channel
- hilight: nick spam
- nick: nick change spam
- cycle: join/part flood
- massJoin
- evades of quiet/bans via gateway/ ( if resolveIp is True )
- clones detection

You should tweak settings to fits your needs, do not use default values. It really depends channel's population and usage ...

Each of those detections has the same kind of settings: there is *Permit (-1 to disable), *Life (which is the time interval over which the bot will track previous messages/behaviour), *Mode (which allows you to select which action you want to use against the user). The action modes that can be set are:

- q : quiet the user
- b : ban the user
- k : kick the user
- r : remove (force part) the user, if the IRCd has the feature. 'REMOVE $channel $nick :$reason'
- d : debug > forward action to logChannel if configured

For bans (b and q mode), you can choose the *Duration of the quiet/ban, and add a *Mark on the related quiet/ban. The 'bad' settings, when enabled (badPermit > -1) keeps track of users who did something wrong during badLife, and can end to badMode if the user exceeds the limit.

Example: flood control: to quiet for 1 minute anyone who sends more than 4 messages in 7 seconds to #channel; if the user continues to flood, after 2 times on 5 minutes he will be banned:

    !config channel #channel supybot.plugins.ChanTracker.floodPermit 4 <-- max number of messages allowed
    !config channel #channel supybot.plugins.ChanTracker.floodLife 7 <-- in 7 seconds
    !config channel #channel supybot.plugins.ChanTracker.floodMode q <-- quiet the user
    !config channel #channel supybot.plugins.ChanTracker.floodDuration 60 <-- for 60 seconds
    !config channel #channel supybot.plugins.ChanTracker.badPermit 2 <-- if user does that 3 times, 
    !config channel #channel supybot.plugins.ChanTracker.badLife 300 <-- during 5 minutes
    !config channel #channel supybot.plugins.ChanTracker.badMode b <-- ban them 

Additionally, the bot can track how many bad actions occur over a period of time and if a threshold is passed, this constitutes an attack on the channel. The attack* settings, when enabled keeps track of bad actions, and if the number exceeds attackPermit within attackLife, some specific channel modes are set for an attackDuration.

Example: not flooding: catch a wave of bots which sends the same message from different hosts:

    !config channel #channel supybot.plugins.ChanTracker.massRepeatChars 200 <-- enable check only if there is at least 200 chars
    !config channel #channel supybot.plugins.ChanTracker.massRepeatPermit 1 <-- if found 2 times
    !config channel #channel supybot.plugins.ChanTracker.massRepeatLife 60 <-- don't keep messages too long in memory, to avoid false positive
    !config channel #channel supybot.plugins.ChanTracker.massRepeatPercent 0.85 <-- set a low value for similarity, in order to catch them if there is some random chars in the messages
    !config channel #channel supybot.plugins.ChanTracker.massRepeatMode b
    !config channel #channel supybot.plugins.ChanTracker.massRepeatDuration 1800 <- ban for 30 minutes
    !config channel #channel supybot.plugins.ChanTracker.attackPermit 2 <- if bot triggers 3 actions during 
    !config channel #channel supybot.plugins.ChanTracker.attackLife 300 <- 5 minutes
    !config channel #channel supybot.plugins.chantracker.attackMode +rq $~a <- then bot will set those modes
    !config channel #channel supybot.plugins.chantracker.attackDuration 1800 <- for 30 minutes
    !config channel #channel supybot.plugins.chantracker.attackUnMode -rq $~a <- and bot will set those modes after 30 minutes
    
Example: a user repeating the same thing: (use repeat detection rather than massRepeat for this):

    !config channel #channel supybot.plugins.ChanTracker.repeatPermit 3 <-- triggered after 3 similar message 
    !config channel #channel supybot.plugins.ChanTracker.repeatLife 40 <-- keep previous messages during 40 seconds
    !config channel #channel supybot.plugins.ChanTracker.repeatPercent 0.88 <-- 1.00 for identical message, don't go too lower, you will get false positive
    !config channel #channel supybot.plugins.ChanTracker.repeatMode q <-- quiet
    !config channel #channel supybot.plugins.ChanTracker.repeatDuration 180 <-- for 3 minutes

Even with all these channel protection features, the bot will do nothing against users with protected capabilities (#channel,protected).

## Other tips ##

Maintaining separate bots for the banning/bantracking functions and other factoid, snarfing or amusement functions is good practice.

If the main purpose of your bot is to manage bans etc, and never interacts with users you should, as owner remove all plugin with 'owner defaultcapabilities remove <pluginname>', it will prevent the bot to answer to various command, and being used as a flood tool by others (like !echo SPAM). You could otherwise change the value of `config help supybot.capabilities.default` but be prepared to waste a lot of time each time you add a new user account on your bot.

If 'supybot.capabilities.default' is changed to False, then, when you want to grant access to command for someone, you must do it that way:

    !admin capability add accountname User
    !admin capability add accountname User.whoami
    !admin capability add accountname whoami

If your bot manage differents channels or community, remove all User.action from defaultcapabilities, create one user per channel/community, and add ops's hostmasks into it, it's easier to manage that way. Until you have someone with rights in 2 community/channels who will need a separate account.

You should keep your bot as quiet as possible. It should not reply to errors, users without capabilities, etc:

    !config supybot.reply.error.noCapability True
    !config supybot.replies.genericNoCapability ""
    !config supybot.abuse.flood.command.invalid.notify False
    !config supybot.reply.whenNotCommand False
    !config supybot.reply.error.detailed False
    !config supybot.replies.error ""
    !config defaultcapability remove channel.nicks
    !config defaultcapability remove channel.alert
    !config defaultcapability remove alias.add
    !config defaultcapability remove config
    !config defaultcapability remove help
    !config defaultcapability remove list

There are other commands that are prone to abuse as well. It's better to use the following command:

    !config supybot.capabilities.default False

This command works with any version of supybot, vanilla, limnoria, etc.

## Bugs and Features ##

Requests can be made via https://github.com/ncoevoet/ChanTracker or in #chantracker on chat.freenode.net.
