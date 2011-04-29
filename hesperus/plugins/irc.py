from ircbot import SingleServerIRCBot as IRCBot
from irclib import nm_to_n, irc_lower
from ..core import ConfigurationError, ET
from ..plugin import Plugin
import re

class IRCPluginBot(IRCBot):
    def __init__(self, plugin, channels):
        IRCBot.__init__(self, [(plugin.server, plugin.port)], plugin.nick, plugin.nick)
        self.initial_channels = channels
        self.plugin = plugin
    
    def on_nicknameinuse(self, c, e):
        c.nick(c.get_nickname() + "_")
    
    def on_welcome(self, c, e):
        self.plugin.log_message("connected to", self.plugin.server)
        if self.plugin.nickserv_password:
            self.plugin.log_verbose("sending password to NickServ...")
            self.connection.privmsg("NickServ", "identify " + self.plugin.nickserv_password)
        for chan in self.initial_channels:
            c.join(chan)
    
    def on_privmsg(self, c, e):
        source = nm_to_n(e.source())
        self.do_command(source, None, e.arguments()[0].strip())
        
    def on_pubmsg(self, c, e):
        channel = e.target()
        source = nm_to_n(e.source())
        def reply(msg):
            self.connection.privmsg(channel, msg)
        self.plugin.do_input([channel], source, e.arguments()[0].strip(), False, reply)
    
    def do_command(self, source, channel, cmd):
        if cmd == "":
            return
        
        def reply(msg):
            if channel == None:
                self.connection.privmsg(source, msg)
            else:
                self.connection.privmsg(channel, "%s: %s" % (source, msg))
        
        channels = []
        if channel != None:
            channels.append(channel)
        else:
            for chan in self.channels:
                if self.channels[chan].has_user(source):
                    channels.append(chan)
        self.plugin.do_input(channels, source, cmd, True, reply)

class IRCPlugin(Plugin):
    @Plugin.config_types(server=str, port=int, nick=str, nickserv_password=str, channelmap=ET.Element, nickmap=ET.Element, inline_commands=bool)
    def __init__(self, core, server='irc.freenode.net', port=6667, nick='hesperus', nickserv_password=None, channelmap=None, nickmap=None, inline_commands=False):
        super(IRCPlugin, self).__init__(core, daemon=True)
        
        self.server = server
        self.port = port
        self.nick = nick
        self.nickserv_password = nickserv_password
        self.chanmap = {}
        self.nickmap = {}
        self.inline_commands = inline_commands

        if channelmap == None:
            channelmap = []
        for el in channelmap:
            if not el.tag.lower() == 'channel':
                raise ConfigurationError('channelmap must contain channel tags')
            channel = el.get('name', None)
            irc_channel = el.text
            if not channel or not irc_channel:
                raise ConfigurationError('invalid channel tag')
            
            if not channel in self.chanmap:
                self.chanmap[channel] = [irc_channel]
            else:
                self.chanmap[channel].append(irc_channel)
        
        if nickmap == None:
            nickmap = []
        for el in nickmap:
            if not el.tag.lower() == 'nick':
                raise ConfigurationError('nickmap must contain nick tags')
            channel = el.get('channel', None)
            irc_nick = el.text
            if not channel or not irc_nick:
                raise ConfigurationError('invalid nick tag')
            
            if not channel in self.nickmap:
                self.nickmap[channel] = [irc_nick]
            else:
                self.nickmap[channel].append(irc_nick)
        
        channels = []
        for k in self.chanmap:
            self.subscribe(k)
            for chan in self.chanmap[k]:
                if not chan in channels:
                    channels.append(chan)
        for k in self.nickmap:
            self.subscribe(k)

        self.bot = IRCPluginBot(self, channels)
        
    def run(self):
        self.log_verbose("connecting...")
        self.bot.start()
    
    # FIXME stop properly -- might need a different irc lib
    #def stop(self):
    #    super(IRCPlugin, self).stop()
    
    def do_input(self, irc_channels, irc_nick, msg, direct, reply):
        chans = []
        for irc_channel in irc_channels:
            for k in self.chanmap:
                if irc_channel in self.chanmap[k] and not k in chans:
                    chans.append(k)
        for k in self.nickmap:
            if irc_nick in self.nickmap[k] and not k in chans:
                chans.append(k)
        
        # some indirect messages may actually be direct, or have
        # embedded direct messages
        if not direct:
            direct_re = r"(\S+)\s*(?:,|:)\s*(.+)"
            whole = re.match(r"^" + direct_re + "$", msg)
            old_reply = reply
            if whole and whole.group(1).lower() == self.nick.lower():
                direct = True
                msg = whole.group(2)
                reply = lambda s: old_reply(irc_nick + ": " + s)
            elif self.inline_commands:
                part = re.search("(?:\(|\[)" + direct_re + "(?:\)|\])", msg)
                if part and part.group(1).lower() == self.nick.lower():
                    part_msg = part.group(2)
                    part_reply = lambda s: old_reply(irc_nick + ": " + s)
                    self.parent.handle_incoming(chans, part_msg, True, part_reply)
        
        self.parent.handle_incoming(chans, msg, direct, reply)
    
    def send_outgoing(self, chan, msg):
        if chan in self.chanmap:
            for irc_chan in self.chanmap[chan]:
                self.bot.connection.notice(irc_chan, msg)
        if chan in self.nickmap:
            for irc_nick in self.nickmap[chan]:
                self.bot.connection.notice(irc_nick, msg)
