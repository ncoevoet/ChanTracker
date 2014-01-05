### ChanTracker : a supybot plugin which do ban tracker ###

This supybot plugin keeps records of channel mode changes, in a sqlite database and permits to manage them over time. It stores affected users, permits to do deep search on them, review actives ones, edit duration, show log, mark them, etc

## Commands ##

	!affect <id> returns affected users by a mode placed
	!b,e,i,q [<channel>] <nick|hostmask>[,<nick|hostmask>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1> or empty means forever] <reason>) -- +mode targets for duration <reason> is mandatory
	!ub,ue,ui,uq [<channel>] <nick|hostmask|*> [<nick|hostmask>]) -- sets -mode on them, if * found, remove them all
	!check [<channel>] <pattern> returns list of users who will be affected by such pattern
	!edit <id> [,<id>] [<years>y] [<weeks>w] [<days>d] [<hours>h] [<minutes>m] [<seconds>s] [<-1>] means forever) -- change expiration of some active modes
	!info <id> returns information about a mode change
	!mark id> [,<id>] <message> add a comment about a mode change
	!pending [<channel>] [<mode>] [<nick|hostmask>]) -- returns active items for mode if given otherwise all modes are returned, if hostmask given, filtered by oper
	!query <text> returns matched modes changes with deep search
	!match [<channel>] <nick|hostmask> returns list of modes that affects the nick,hostmask given
	!detail <id> returns log from a mode change
	!remove [<channel>] <nick> [<reason>] do a force part on <nick> in <channel> with <reason> if provided
	
## Settings ##

You should increase ping interval, as on channel join bot asks many things and sometimes server takes lot of time to answer

	!config supybot.protocols.irc.ping.interval 3600

By default, **bot will not stay opped**, but you can configure that globaly or per channel :

	!config supybot.plugins.ChanTracker.keepOp False
	!config channel #myChannel supybot.plugins.ChanTracker.keepOp True

If you don't want the bot to manage his own op status, you can change the config value :

	!config supybot.plugins.ChanTracker.doNothingAboutOwnOpStatus True
	!config channel #myChannel supybot.plugins.ChanTracker.doNothingAboutOwnOpStatus False

Tracked modes are currently defined here ( +qb, and eI if opped ):

	!config supybot.plugins.ChanTracker.modesToAsk
	!config supybot.plugins.ChanTracker.modesToAskWhenOpped

The command used by the bot to op itself is editeable here :

	!config supybot.plugins.ChanTracker.opCommand by default it's "CS OP $channel $nick" 

Where $channel and $nick will be replaced by targeted channel and bot's nick at runtime

For more readable date, you should change this :

	!config supybot.reply.format.time.elapsed.short True

Bot can forward a lot of important informations about channel activity into a secret channel, like an -ops channel, you can set it globaly or per channel:

	!config supybot.plugins.ChanTracker.logChannel #myGeneralSecretChannel
	!config channel #myChannel supybot.plugins.ChanTracker.logChannel #myChannel-ops

You can tweak which informations you would like to be forwarded, some are activated by default like topic changes, mode changes, etc , some not, take a look at :

	!search supybot.plugins.ChanTracker.announce

Bot can send a private message to an op who sets a tracked mode, if configured for, note the op must be know as channel's op by the bot :

	!config channel #myChannel supybot.plugins.ChanTracker.askOpAboutMode True

Bot can set a duration for new tracked mode changes, in order to auto remove them :

	!config channel #myChannel supybot.plugins.ChanTracker.autoExpire 3600 ( 1h )

If ircd is great, bot can track account changes and get gecos/username informations when someone joins a channel, it supports ircd CAP features, details can be found here : http://tools.ietf.org/html/draft-mitchell-irc-capabilities-01

Bot also supports extended bans/quiets like $r,$x,$a, etc if you want it to support your ircd extended bans, please, fill an issue or contact me

It also has a lot of channel protection features, with per channel settings, take a look at config.py for details, but it is able to handle flood, flood from throttle client ( like copy/paste ), repeat message, repeat message from multi users, UPPER CASE spam, channel's CTCP, channel's notices, hilight spam, nick changes spam, join/part flood, mass join, and two more features, bad user flag and channel under attack modes

An example about flood control, You want to quiet for 1 minute anyone that send more than 4 messages in 7 seconds in #channel, and if the user continue to flood, after 2 times he will be banned

	!config channel #channel supybot.plugins.ChanTracker.floodPermit 4
	!config channel #channel supybot.plugins.ChanTracker.floodLife 7
	!config channel #channel supybot.plugins.ChanTracker.floodMode q
	!config channel #channel supybot.plugins.ChanTracker.floodDuration 60
	!config channel #channel supybot.plugins.ChanTracker.badPermit 2
	
You can use k and r as *Mode, which will kick or force part instead of quiet/ban.
	
Bot will do nothing against user with protected capabilities ( #channel,protected ) and people in +eI list ( supybot.plugins.ChanTracker.modesToAskWhenOpped )
	
That means if the bot will quiet anyone who flood, and if the user flood more than 2 times during badLife, bot will use badMode on him

Bot will kick by users affected by +b see :

	!config supybot.plugins.ChanTracker.kickMode
	!config supybot.plugins.ChanTracker.kickMessage

Note : bot will only kick people if the ban was set by itself, if an op place a ban, bot will not kick affected users

It works with any version of supybot, vannila, limnoria etc

BUGS & FEATURES requests can be reported on https://github.com/ncoevoet/ChanTracker or in private message to niko, on chat.freenode.net
    
