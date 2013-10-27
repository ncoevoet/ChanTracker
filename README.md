This supybot plugin keeps records of channel mode changes, in a sqlite database and permits to manage them over time. \
It stores affected users, permits to do deep search on them, review actives ones, edit, log, mark lot of them in row.

By default, bot will not stay opped, but you can configure that globaly or per channel :

	!config supybot.plugins.ChanTracker.keepOp False
	!config channel #myChannel supybot.plugins.ChanTracker.keepOp True

Tracked modes are currently defined here ( +qbeI by default ):

	!config supybot.plugins.ChanTracker.modesToAsk
	!config supybot.plugins.ChanTracker.modesToAskWhenOpped

The command used by the bot to op itself is editeable here :

	!config supybot.plugins.ChanTracker.opCommand by default it's "CS OP $channel $nick" 

Where $channel and $nick will be replaced by targeted channel and bot's nick at runtime

For more fancy date, you should change this :

	!config supybot.reply.format.time.elapsed.short True, 

A lot of fancy informations can be send by the bot about your #channel activity to #logChannel, if set up, globaly or per channel, bot must be in both, obloviously:

	!config channel #myChannel supybot.plugins.ChanTracker.logChannel #mySecretChannelForOp

Bot can send a private message to an op who sets a tracked mode, if configured for :

	!config channel #myChannel supybot.plugins.ChanTracker.askOpAboutMode True

Bot can set a duration for new tracked mode changes, in order to auto remove them :

	!config channel #myChannel supybot.plugins.ChanTracker.autoExpire 3600 ( 1h )

If ircd is great, bot can track account changes and get gecos/username informations when someone joins a channel, \
it supports ircd CAP features, details can be found here : http://tools.ietf.org/html/draft-mitchell-irc-capabilities-01

It also has a lot of channel protection features, with per channel settings, take a look at config.py for details :

	flood
	low flood ( mostly irc's client with trottle features )
	repeat spam
	repeat spam from multi source
	uppercase spam
	ctcps spam
	notices spam
	hilight spam
	nick changes flood
	join/part flood
	mass join
	bad user flag
	under attack channel

Users who matchs patterns presents on supybot.plugins.ChanTracker.modesToAskWhenOpped are exempted from those triggers : \
In that case you should set bot to keep op, in order to tracks of exempted users.

An example about flood control : \
You want to quiet for 1 minute anyone that send more than 4 messages in 7 seconds in your #channel, and if the user continue to flood, ban him

	!config channel #channel supybot.plugins.ChanTracker.floodPermit 4
	!config channel #channel supybot.plugins.ChanTracker.floodLife 7
	!config channel #channel supybot.plugins.ChanTracker.floodMode q
	!config channel #channel supybot.plugins.ChanTracker.floodDuration 60
	
	!config channel #channel supybot.plugins.ChanTracker.badPermit 2
	
That means if the bot will quiet anyone who flood, and if the user flood more than 2 times during badLife, bot will use badMode on him

Bot will kick by users affected by +b see :

	!config supybot.plugins.ChanTracker.kickMode
	!config supybot.plugins.ChanTracker.kickMessage

Note : if an op sets mode +b *!*@* on #channel by mistake and bot has kickMode enabled in it, it will kick everyone, be warned.

It works with any version of supybot, vannila, limnoria etc

BUGS & FEATURES requests can be reported on https://github.com/ncoevoet/ChanTracker or in private message to niko, on chat.freenode.net
    
