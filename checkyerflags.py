import logging
import os
import sys
import json
import io
import gzip
import threading
import traceback

import flagbot.flags as check_flags
import flagbot.redunda as redunda
import flagbot.flags_auto_check as fac

#Import config file with custom error message
try:
    import config as config
except ModuleNotFoundError:
    raise Exception("The config module couldn't be imported. Have you renamed config.example.py to config.py?")


from flagbot.utils import utils
from urllib.request import urlopen
from markdownify import markdownify as md
from chatexchange.chatexchange.client import Client
from chatexchange.chatexchange.events import MessagePosted, MessageEdited

utils = utils()

def main():

    #Get config for the mode (debug/prod)
    try:
        if sys.argv[1] == '--debug':
            print("Loading debug config...")
            utils.config = config.debug_config
        else:
            raise IndexError
    except IndexError:
        print("Loading productive config... \nIf you wanted to load the debug config, use the '--debug' command line option")
        utils.config = config.prod_config

    #region Login and connection to chat
    utils.room_number = utils.config["room"]
    client = Client(utils.config["chatHost"])
    client.login(utils.config["email"], utils.config["password"])
    utils.client = client
    room = client.get_room(utils.config["room"])
    room.join()
    room.watch_socket(on_message)
    print(room.get_current_user_names())
    utils.room_owners = room.owners
    #endregion

    #Store current quota as variabke
    quota_obj = json.loads(gzip.GzipFile(fileobj=io.BytesIO(urlopen("https://api.stackexchange.com/2.2/users/1?order=desc&sort=reputation&site=stackoverflow&key={}".format(utils.config["stackExchangeApiKey"])).read())).read().decode("utf-8"))


    if quota_obj['quota_remaining'] is not None:
        utils.quota = quota_obj['quota_remaining']

    logging.basicConfig(filename="CheckYerFlags.log", level=logging.INFO, filemode="a")
    logging.getLogger("chatexchange").setLevel(logging.WARNING)
    logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))

    logging.info("Joined room '{}' on {}".format(room.name, utils.config["chatHost"]))

    #region Background threads

    #Auto-Checking (currently disabled)
    """cu = room.get_current_users()
    nb = utils.id_list_without_bots(cu)

    thread_list = []

    stop_auto_checking_lp = threading.Event()
    auto_check_lp_thread = fac.AutoFlagThread(stop_auto_checking_lp, utils, utils.config, logging, 0, nb, thread_list)
    auto_check_lp_thread.start()
    thread_list.append(auto_check_lp_thread)

    stop_auto_checking_hp = threading.Event()
    auto_check_hp_thread = fac.AutoFlagThread(stop_auto_checking_hp, utils, utils.config, logging, 1, [], thread_list)
    auto_check_hp_thread.start()
    thread_list.append(auto_check_hp_thread)
    #auto_check_lp_thread.check_flags_lp()"""

    #Redunda pining
    stop_redunda = threading.Event()
    redunda_thread = redunda.RedundaThread(stop_redunda, utils.config, logging)
    redunda_thread.start()
    #endregion

    try:
        if sys.argv[1] == '--debug':
            room.send_message("[ [CheckYerFlags](https://stackapps.com/q/7792) ] started in debug mode.")
        else:
            raise IndexError
    except IndexError:
        room.send_message("[ [CheckYerFlags](https://stackapps.com/q/7792) ] started.")

    while True:
        message = input("<< ")

        if message == "restart":
            os._exit(1)
        else:
            room.send_message(message)

    #client.logout()
    #stop_redunda.set()

def on_message(message, client):
    if not isinstance(message, MessagePosted) and not isinstance(message, MessageEdited):
        # We ignore non-MessagePosted events.
        return
    message_val = message.content
    words = message.content.split()

    if message is None or message.content is None:
        logging.warning("ChatExchange message object or content property is None.")
        logging.warning(message)
        return

    if message.user.id == 9220325:
        utils.last_bot_message = message

    #Check if alias is valid
    if not utils.alias_valid(words[0]):
        return

    command = words[1]

    try:
        #Here are the commands defined
        if command in ["del", "delete", "poof"]:
            msg = client.get_message(utils.last_bot_message._message_id)
            if msg is not None:
                msg.delete()
        elif command in ["amiprivileged"]:
            logging.info("amiprivileged command was called")

            if utils.is_privileged(message):
                utils.reply_with(message, "You are privileged.")
            else:
                utils.reply_with(message, "You are not privileged. Ping Filnor if you believe that's an error.")
        elif command in ["a", "alive"]:
            logging.info("alive command was called")
            utils.reply_with(message, "instance of {} is running on **{}/{}**".format(utils.config["botVersion"], utils.config["botParent"], utils.config["botMachine"]))
        elif command in ["v", "version"]:
            logging.info("version command was called")
            utils.reply_with(message, "Current version is {}".format(utils.config["botVersion"]))
        elif command in ["say"]:
            logging.info("say command was called")
            if message.user.id != 9220325: # Don't process commands by the bot account itself
                say_message = md(' '.join(map(str, words[2:])))
                utils.post_message(say_message)
        elif command in ["welcome"]:
            logging.info("welcome command was called")
            #Only run in SOBotics
            if utils.room_number == 111347:
                utils.post_message("Welcome to SOBotics! You can learn more about SOBotics and what we and [all the bots](https://sobotics.org/all-bots/) are doing here at our website, https://sobotics.org/. If you'd like to help out with flagging, reporting, or anything else, let us know! We have tons of [userscripts](https://sobotics.org/userscripts/) to make things easier, and you'll always find someone around who will help you to install them and explain how they work.")
            else:
                utils.post_message("This command is not supported in this room")
        elif command in ["quota"]:
            logging.info("quota command was called")
            utils.post_message("The remaining API quota is {}.".format(utils.quota))
        elif command in ["kill", "stop"]:
            logging.info("kill command was called")
            logging.warning("Termination or stop requested by {}".format(message.user.name))

            if utils.is_privileged(message):
                try:
                    utils.client.get_room(utils.room_number).leave()
                except BaseException:
                    pass
                raise os._exit(0)
            else:
                utils.reply_with(message, "This command is restricted to moderators, room owners and maintainers.")
        elif command in ["bye"]:
            logging.info("leave command was called")
            logging.warning("Leave requested by {}".format(message.user.name))

            # Restrict function to (site) moderators, room owners and maintainers
            if utils.is_privileged(message):
                utils.post_message("Bye")
                utils.client.get_room(utils.room_number).leave()
            else:
                utils.reply_with(message, "This command is restricted to moderators, room owners and maintainers.")
        elif command in ["command", "commands", "help"]:
            logging.info("command list command was called")
            utils.reply_with(message, "You can find a list of my commands [here](http://checkyerflags.sobotics.org/#commands)")
        elif command in ["s", "status"] and words[2] in ["m", "mine"]:
            logging.info("status mine command was called")
            check_flags.check_own_flags(message, utils)
        elif command in ["s", "status"] and words[2] not in ["m", "mine"]:
            logging.info("status user id command was called")
            check_flags.check_flags(None, utils, None, words[2])
        elif command in ["r", "rank"] and words[2] in ["n", "next"]:
            logging.info("rank next command was called")
            check_flags.check_own_flags_next_rank(message, utils)
        #region Fun commands
        elif message.content.startswith("🚂"):
            logging.info("train command was called")
            utils.post_message("🚃")
        elif command in ["why"]:
            logging.info("why command was called")
            utils.reply_with(message, "[Because of you](https://www.youtube.com/watch?v=Ra-Om7UMSJc)")
        elif command in ["good"] and words[2] in ["bot", "job"]:
            logging.info("good bot command was called")
            utils.reply_with(message, "Thank you")
        elif command in ["thanks", "thx"] or "{} {}".format(words[1], words[2]) in ["thank you"] :
            logging.info("thanks command was called")
            utils.reply_with(message, "You're welcome.")
        elif "shrug" in message.content:
            logging.info("shrug command was called")
            utils.post_message("¯\\ \_(ツ)\_ /¯", True)
        elif "kappa.gif" in message.content:
            logging.info("kappa.gif command was called")
            utils.reply_with(message, "https://i.imgur.com/8TRbWHM.gif")
        #endregion
    except (KeyboardInterrupt, SystemExit):
        os._exit(0)
    except BaseException as e:
        logging.error("CRITICAL ERROR: {}".format(e))
        if message is not None and message.id is not None:
            logging.error("Caused by message id ".format(message.id))
            logging.error(traceback.format_exc())
        try:
            utils.post_message("Error on processing the last command ({}); rebooting instance... (cc @Filnor)".format(e))
            os._exit(1)

        except AttributeError:
            pass


if __name__ == '__main__':
    main()