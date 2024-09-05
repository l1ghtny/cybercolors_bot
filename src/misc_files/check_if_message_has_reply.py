def check_replies(message):
    has_replies = False
    try:
        if message.reference.message_id is not None:
            has_replies = not has_replies
    except AttributeError:
        has_replies = has_replies
    return has_replies
