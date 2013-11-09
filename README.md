### ChanTracker : a supybot plugin which do ban tracker ###

This supybot plugin keeps records of channel mode changes, in a sqlite database and permits to manage them over time. It stores affected users, permits to do deep search on them, review actives ones, edit, log, mark lot of them in row.

By default, **bot will not stay opped**, but you can configure that globaly or per channel :

	!config supybot.plugins.ChanTracker.keepOp False
	!config channel #myChannel supybot.plugins.ChanTracker.keepOp True

Tracked modes are currently defined here ( +qb, and eI ( if opped ) by default ):

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

It also has a lot of channel protection features, with per channel settings, take a look at config.py for details, but it is able to handle flood, flood from throttle client ( like copy/paste ), repeat message, repeat message from multi users, UPPER CASE spam, channel's CTCP, channel's notices, hilight spam, nick changes spam, join/part flood, mass join, and two more features, bad user flag and channel under attack modes

An example about flood control, You want to quiet for 1 minute anyone that send more than 4 messages in 7 seconds in #channel, and if the user continue to flood, after 2 times he will be banned

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
    
