# ChanTracker : a supybot plugin for ban tracking #

This supybot plugin keeps records of channel mode changes in a sqlite database and permits management of them over time. It stores affected users, enabling deep searching through them, reviewing actives, editing duration, showing logs, marking/annotating them, etc

The plugin is used in various and large channels on freenode ( #bitcoin, #bitcoin-otc, #bitcoin-pricetalk, #defocus, #wrongplanet, + 40 french channels and )

## Commands ##

	!affect <id> returns affected users by a mode placed
	!b,e,i,q [<channel>] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1> or empty means forever] <reason>) -- +mode targets for duration <reason> is mandatory
	!ub,ue,ui,uq [<channel>] <nick|hostmask|*> [<nick|hostmask>]) -- sets -mode on them, if * found, remove them all
	!check [<channel>] <pattern> returns list of users who will be affected by such pattern
	!edit <id> [,<id>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1>] means forever) -- change expiration of some active modes
	!info <id> returns information about a mode change
	!mark <id> [,<id>] <message> add a comment about a mode change
	!pending [<channel>] (pending [--mode=<e|b|q|l>] [--oper=<nick|hostmask>] [--never] [<channel>] ) -- returns active items for --mode if given, filtered by --oper if given, --never never expire only if given
	!query [--deep] [--never] [--active] [--channel=<channel>] <pattern|hostmask|comment>) -- search inside ban database, --deep to search on log, --never returns items set forever and active, --active returns only active modes, --channel reduces results to a specific channel
	!match [<channel>] <nick|hostmask> returns list of modes that affects the nick,hostmask given
	!detail <id> returns log from a mode change
	!remove [<channel>] <nick> [<reason>] do a force part on <nick> in <channel> with <reason> if provided

## General Usage ##

The bot can be used to place and remove bans (rather than the the op setting channel modes directly). For example, to quiet the argumentative user 'ian' for 10 minutes and ban the spammer 'ham' for a month:

	!q ian 10m argumentative again
	!b ham 30d silly spammer
	!b foo 1h30m must stop

These can also be done via a private message to the bot, although you must include the channel in the message:

	/msg mybigbadbot q #myChannel ian 10m argumentative again
	/msg mybigbadbot b #myChannel ham 30d silly spammer

For each of these bans, the nick is used to generate a *!*@host ban. The desired mask can be given directly to the bot instead of the nick. Also note that, by default, the bot will also kick users that have a +b set against them (details below).

Alternatively, the bot can be used just to track the mode changes, with ops using the capabilities of their own irc clients to set bans. The same sequence as before:

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

You should increase the ping interval because when the bot joins a channel, it requests lots of data and sometimes the server takes time to answer

	!config supybot.protocols.irc.ping.interval 3600

By default, **bot will not stay opped**, but you can configure that globally or per channel:

	!config supybot.plugins.ChanTracker.keepOp False
	!config channel #myChannel supybot.plugins.ChanTracker.keepOp True

If you don't want the bot to manage its own op status, you can change the config value :

	!config supybot.plugins.ChanTracker.doNothingAboutOwnOpStatus True
	!config channel #myChannel supybot.plugins.ChanTracker.doNothingAboutOwnOpStatus False

The channel modes that will be tracked are currently defined here (qb, and eI if opped -- only ops can see the e and I lists for a channel):

	!config supybot.plugins.ChanTracker.modesToAsk
	!config supybot.plugins.ChanTracker.modesToAskWhenOpped

The command used by the bot to op itself is editable here:

	!config supybot.plugins.ChanTracker.opCommand by default it's "CS OP $channel $nick" 

where $channel and $nick will be replaced by targeted channel and bot's nick at runtime

For more readable date information in output, you should change this:

	!config supybot.reply.format.time.elapsed.short True

The bot can have a "reporting channel" like an -ops channel, where it forwards a lot of important information about channel activity. You can set it globally or per channel:

	!config supybot.plugins.ChanTracker.logChannel #myGeneralSecretChannel
	!config channel #myChannel supybot.plugins.ChanTracker.logChannel #myChannel-ops

You can tweak which information you would like to be forwarded to the reporting channel. Some reporting is activated by default like topic changes, mode changes, etc, some not, like bot's ban/quiet edit/mark etc, take a look at:

	!search supybot.plugins.ChanTracker.announce
	!config help supybot.plugins.ChanTracker.announceModes

If desired, the bot can send a private message to the op that sets a tracked mode. Note the op must be known as channel's op by the bot; the bot owner automatically has that capability:

	!config channel #myChannel supybot.plugins.ChanTracker.askOpAboutMode True

You can add op capability to someone that way:
	
	!user register opaccount password
	!hostmask add opaccount *!*@something
	!admin capability add opaccount #myChannel,op

The bot can set a default duration for new tracked mode changes, in order to auto remove them:

	!config channel #myChannel supybot.plugins.ChanTracker.autoExpire 3600 (1h)

The plugin can create persistent bans to help manage large ban lists that exceed the ircd's limits on the length of ban lists. The plugin can remove bans from the ircd ban list while checking all joining users against its own lists. If a user matches, then the ircd ban is reinstated:

	!config channel #myChannel supybot.plugins.ChanTracker.useChannelBansForPermanentBan true
	!channel ban add #myChannel *!*@mask

With autoExpire enabled, the ircd list is pruned as appropriate and bans are rotated in a way to not reveal the pattern used for the match. Due to a supybot limitation, extended bans are not supported with this feature.

If supported by the ircd, the bot can track account changes and get GECOS and username information when a user joins the channel. This requires ircd CAP features:  http://tools.ietf.org/html/draft-mitchell-irc-capabilities-01

The plugin also supports extended bans/quiets including $r, $x, $a (real name, full match and account name, respectively). If you want the plugin to support your ircd extended bans, please, report a bug or contact me directly.

By default, if the bot is asked to set a ban (+b), it will also kick affected users (Note: bot will only kick people if the ban was set by the bot -- if an op places the ban, the bot will not kick affected users). See:

	!config supybot.plugins.ChanTracker.kickMode
	!config supybot.plugins.ChanTracker.kickMessage

The bot will remove exception modes (that is exempt e, or invite exempt I) for people banned if 'doActionAgainstAffected' for given channel is True.


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

Each of those detections has the same kind of settings: there is *Permit (-1 to disable), *Life (which is the time interval over which the bot will track previous messages/behaviour), *Mode (which allows you to select which action you want to use against the user). The action modes that can be set are:

- q : quiet the user
- b : ban the user
- k : kick the user
- r : remove (force part) the user, if the ircd has the feature. 'REMOVE $channel $nick :$reason'

For bans (b and q mode), you can choose the *Duration of the quiet/ban, and add a *Mark on the related quiet/ban. The 'bad' settings, when enabled (badPermit > -1) keeps track of users who did something wrong during badLife, and can end to badMode if the user exceeds the limit.

Example: flood control: to quiet for 1 minute anyone who sends more than 4 messages in 7 seconds to #channel; if the user continues to flood, after 2 times they will be banned

	!config channel #channel supybot.plugins.ChanTracker.floodPermit 4 <-- max number of messages allowed
	!config channel #channel supybot.plugins.ChanTracker.floodLife 7 <-- in 7 seconds
	!config channel #channel supybot.plugins.ChanTracker.floodMode q <-- quiet the user
	!config channel #channel supybot.plugins.ChanTracker.floodDuration 60 <-- for 60 seconds
	!config channel #channel supybot.plugins.ChanTracker.badPermit 2 <-- if user does that 3 times, 
	!config channel #channel supybot.plugins.ChanTracker.badMode b <-- ban them 

Additionally, the can track how many bad actions occur over a period of time and if a threshold is passed, this constitutes an attack on the channel. The attack* settings, when enabled keeps track of bad actions, and if the number exceeds attackPermit within attackLife, some specific channel modes are set for an attackDuration.

Example: not flooding: catch a wave of bots which sends the same message from different hosts:

	!config channel #channel supybot.plugins.ChanTracker.massRepeatChars 200 <-- enable check only if there is at least 200 chars
	!config channel #channel supybot.plugins.ChanTracker.massRepeatPermit 0 <-- that means if first message matchs the seconds, it will trigger it
	!config channel #channel supybot.plugins.ChanTracker.massRepeatLife 60 <-- don't keep messages too long in memory, to avoid false positive
	!config channel #channel supybot.plugins.ChanTracker.massRepeatPercent 0.85 <-- set a low value for similarity, in order to catch them if there is some random chars in the messages 
	!config channel #channel supybot.plugins.ChanTracker.massRepeatMode b
	!config channel #channel supybot.plugins.ChanTracker.massRepeatDuration 1800  

Example: a user repeating the same thing: (use repeat detection rather than massRepeat for this):

	!config channel #channel supybot.plugins.ChanTracker.repeatPermit 3 <-- triggered after 3 similar message 
	!config channel #channel supybot.plugins.ChanTracker.repeatLife 40 <-- keep previous messages during 60 seconds
	!config channel #channel supybot.plugins.ChanTracker.repeatPercent 0.88 <-- 1.00 for identical message, don't go too lower, you will get false positive
	!config channel #channel supybot.plugins.ChanTracker.repeatMode q <-- quiet
	!config channel #channel supybot.plugins.ChanTracker.repeatDuration 180 <-- for 3 minutes

Even with all these channel protection features, the bot will do nothing against users with protected capabilities (#channel,protected).


## Other tips ##

Maintaining separate bots for the banning/bantracking functions and other factoid, snarfing or amusement functions is good practice.

If the main purpose of your bot is to manage bans etc, and never interacts with users you should, as owner remove all plugin with 'owner defaultcapabilities remove <pluginname>', it will prevent the bot to answer to various command, and being used as a flood tool by others (like !echo SPAM). You could otherwise change the value of `config help supybot.capabilities.default` but be prepared to waste a lot of time each time you add a new user account on your bot.

If your bot manage differents channels or community, remove all User.action from defaultcapabilities, create one user per channel/community, and add ops's hostmasks into it, it's easier to manage that way. Until you have someone with rights in 2 community/channels who will need a separate account.

You should keep your bot quiet as possible, it should not replies to error, user without capabilities, etc :

	supybot.reply.error.noCapability: True
	supybot.reply.whenNotCommand: False
	supybot.reply.error.detailed: False
	
You should also disable help, config, list until needed for registered users on the bot.
	
	
It works with any version of supybot, vanilla, limnoria etc


## Bugs and Features ##

Requests can be made via https://github.com/ncoevoet/ChanTracker or in private message to niko on chat.freenode.net.
