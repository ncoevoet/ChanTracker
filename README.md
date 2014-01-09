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

You can tweak which informations you would like to be forwarded, some are activated by default like topic changes, mode changes, etc, some not, like bot's ban/quiet edit / mark etc, take a look at :

	!search supybot.plugins.ChanTracker.announce

Bot can send a private message to an op who sets a tracked mode, if configured for, note the op must be know as channel's op by the bot :

	!config channel #myChannel supybot.plugins.ChanTracker.askOpAboutMode True

Bot can set a duration for new tracked mode changes, in order to auto remove them :

	!config channel #myChannel supybot.plugins.ChanTracker.autoExpire 3600 ( 1h )

Has bot can check on join if user matchs bans filled via channel add #channel *!*@mask ( see config useChannelBansForPermanentBan ), and ban the user if he matchs, 
with autoExpire enabled, it allows you to manage a larger bans list than what the ircd can provide, with rotated bans, and without reveals the pattern used for match ( the only restriction there is that it doesn't support extended bans due to supybot)

If ircd is great, bot can track account changes and get gecos/username informations when someone joins a channel, it supports ircd CAP features, details can be found here : http://tools.ietf.org/html/draft-mitchell-irc-capabilities-01

Bot also supports extended bans/quiets like $r,$x,$a, etc if you want it to support your ircd extended bans, please, fill an issue or contact me

It has a lot of channel build in protection features, which can be enabled individualy and per channel, or globaly :

- flood detection
- low flood detection
- repeat detection
- massRepeat detection ( when same message comes from differents users )
- capslock detection
- ctcp : channel's ctcp detection
- notices : channel's notices detection
- hilight : nick spam
- nick : nick changes spam
- cycle : join/part flood
- massJoin

each of those detection works with the same kind of settings, there is *Permit ( -1 to disable ), *Life ( which means during how long the bot will keep in mind previous messages/behaviour ), 
*Mode ( which allows you to select which action you want to do against the user :

- q : quiet the user
- b : ban the user
- k : kick the user
- r : force part the user ( if the ircd has the feature ) 'REMOVE $channel $nick :$reason'

for each of those, but only relevant with bq mode, you can choose the *Duration of the quiet/ban, and add a *Mark on the related quiet/ban.

An example about flood control, You want to quiet for 1 minute anyone that send more than 4 messages in 7 seconds in #channel, and if the user continue to flood, after 2 times he will be banned

	!config channel #channel supybot.plugins.ChanTracker.floodPermit 4 <-- max number of messages allowed
	!config channel #channel supybot.plugins.ChanTracker.floodLife 7 <-- in 7 seconds
	!config channel #channel supybot.plugins.ChanTracker.floodMode q <-- quiet the user
	!config channel #channel supybot.plugins.ChanTracker.floodDuration 60 <-- for 60 seconds
	!config channel #channel supybot.plugins.ChanTracker.badPermit 2 <-- if user does that 3 times, 
	!config channel #channel supybot.plugins.ChanTracker.badMode b <-- ban him 

bad* when enabled ( badPermit > -1 ) keeps track of user who did something wrong during badLife, and can end to banMode if the user exceeds the limit.
attack* when enabled keeps track of bad actions, and if channel count of bad actions during attackLife exceeds attackPermit, it sets some specific channels mode during a attackDuration

Another example, you got sometimes a wave of bots which sends the same message from differents hosts:

	!config channel #channel supybot.plugins.ChanTracker.massRepeatChars 200 <-- enable check only if there is at least 200 chars
	!config channel #channel supybot.plugins.ChanTracker.massRepeatPermit 0 <-- that means if first message matchs the seconds, it will trigger it
	!config channel #channel supybot.plugins.ChanTracker.massRepeatLife 4 <-- don't keep messages too long in memory, to avoid false positive
	!config channel #channel supybot.plugins.ChanTracker.massRepeatPercent 0.60 <-- set a low value for similarity, in order to catch them if there is some random chars in the messages 
	!config channel #channel supybot.plugins.ChanTracker.massRepeatMode b
	!config channel #channel supybot.plugins.ChanTracker.massRepeatDuration 600 <-- with massRepeat detection, pattern used when triggering are kept in memory during massPatternDuration, so don't keep them too long in memory

On regular spam purpose, you should not use massRepeat feature, but simply repeat detection:

	!config channel #channel supybot.plugins.ChanTracker.repeatPermit 3 <-- triggered after 3 similar message 
	!config channel #channel supybot.plugins.ChanTracker.repeatLife 120 <-- keep previous messages during 60 seconds
	!config channel #channel supybot.plugins.ChanTracker.repeatPercent 0.88 <-- 1.00 for identical message, don't go too lower, you will get false positive
	!config channel #channel supybot.plugins.ChanTracker.repeatMode q <-- quiet
	!config channel #channel supybot.plugins.ChanTracker.repeatDuration 180 <-- for 3 minutes

Bot will do nothing against user with protected capabilities ( #channel,protected ) and people in +eI list ( supybot.plugins.ChanTracker.modesToAskWhenOpped ) with those protection features enabled.

Bot will kick by users affected by +b see :

	!config supybot.plugins.ChanTracker.kickMode
	!config supybot.plugins.ChanTracker.kickMessage

Note : bot will only kick people if the ban was set by itself, if an op place a ban, bot will not kick affected users

If the main purpose of your bot is to manage bans etc, and never interacts with users you should, as owner remove all plugin with 'owner defaultcapabilities remove <pluginname>', it will prevent the bot to answer to various command, and being used as a flood tool by others. ( like !echo SPAM )

If your bot manage differents channels or community, remove all User.action from defaultcapabilities, create one user per channel/community, and add ops's hostmasks into it, it's easier to manage that way. Until you have someone with rights in 2 community/channels who will need a separate account.

It works with any version of supybot, vannila, limnoria etc

BUGS & FEATURES requests can be reported on https://github.com/ncoevoet/ChanTracker or in private message to niko, on chat.freenode.net
    
