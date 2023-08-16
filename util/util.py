from discord import Interaction, Reaction, User


def check_reaction(emojis: list[str], ctx: Interaction, message_id: int):
    def checker(reaction: Reaction, user: User):
        return user.id == ctx.user.id and str(reaction.emoji) in emojis and reaction.message.id == message_id

    return checker


def custom_emoji(emoji_name: str, emoji_id: int):
    return f'<:{emoji_name}:{emoji_id}>'
