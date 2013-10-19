This supybot plugin keeps records of channel mode changes, in a sqlite database and permits to manage them over time.
it stores affected users, permits to do deep search on them, review actives modes, edit,log, mark lot of them in row, 

It also has a lot of channel protection features, flood, repeat, uppercase, ctcps, notices, hilight, join/part flood, etc all of those settings configurable per channel

It works with any version of supybot, vannila, limnoria etc

After first load, you must type !config supybot.plugins.ChanTracker.CAPS account-notify,extended-join
and reload the plugin

