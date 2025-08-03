import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import shutil
import asyncio
from datetime import datetime, timedelta
import random
from dotenv import load_dotenv

# .envファイルを読み込み
load_dotenv()

# デバッグ: .envファイルの読み込み確認
print(f"[DEBUG] .envファイル読み込み確認:")
print(f"[DEBUG] BOT_TOKEN exists: {bool(os.getenv('BOT_TOKEN'))}")
print(f"[DEBUG] ADMIN_USER_IDS: {os.getenv('ADMIN_USER_IDS')}")
print(f"[DEBUG] GUILD_ID: {os.getenv('GUILD_ID')}")
print(f"[DEBUG] LOG_CHANNEL_ID raw: '{os.getenv('LOG_CHANNEL_ID')}'")
print(f"[DEBUG] Current working directory: {os.getcwd()}")
print(f"[DEBUG] .env file exists: {os.path.exists('.env')}")

# より確実な読み込みを試行
if not os.getenv('LOG_CHANNEL_ID'):
    # 明示的にパスを指定して再読み込み
    env_path = os.path.join(os.getcwd(), '.env')
    print(f"[DEBUG] 明示的パスで再読み込み: {env_path}")
    load_dotenv(env_path)
    print(f"[DEBUG] 再読み込み後 LOG_CHANNEL_ID: '{os.getenv('LOG_CHANNEL_ID')}'")

# Botの設定
intents = discord.Intents.default()
intents.message_content = True

# データファイルのパス
DATA_FILE = 'z_currency_data.json'

# 初期設定
INITIAL_BALANCE = 0  # 初期残高

# 管理者のユーザーIDを.envファイルから読み込み
ADMIN_USER_IDS = []
if os.getenv('ADMIN_USER_IDS'):
    admin_ids_str = os.getenv('ADMIN_USER_IDS')
    ADMIN_USER_IDS = [int(user_id.strip()) for user_id in admin_ids_str.split(',') if user_id.strip()]

# ギルドIDを.envファイルから読み込み（即座同期用）
GUILD_ID = None
if os.getenv('GUILD_ID'):
    try:
        GUILD_ID = int(os.getenv('GUILD_ID'))
    except ValueError:
        print("⚠️ GUILD_IDの形式が正しくありません")

# ログチャンネルIDを.envファイルから読み込み
LOG_CHANNEL_ID = None
if os.getenv('LOG_CHANNEL_ID'):
    try:
        LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID'))
        print(f"[DEBUG] LOG_CHANNEL_ID 読み込み成功: {LOG_CHANNEL_ID}")
    except ValueError as e:
        print(f"⚠️ LOG_CHANNEL_IDの形式が正しくありません: {e}")
        print(f"[DEBUG] 読み込み値: '{os.getenv('LOG_CHANNEL_ID')}'")
else:
    print(f"[DEBUG] LOG_CHANNEL_ID 環境変数が見つかりません")
    print(f"[DEBUG] 利用可能な環境変数: {[key for key in os.environ.keys() if 'LOG' in key.upper()]}")

# ちんちろの役の強さ（表に基づく配当率）
CHINCHIN_HANDS = {
    # 即負け（出した分払う）
    'ピンゾロ': -1,         # 1,1,1 - 即負け
    'シゴロ': -1,           # 4,4,4 - 即負け  
    '役無し': -1,           # 役なし - 即負け
    'ショウペン': -1,       # 井からこぼれる - 即負け
    
    # 通常の目（出した分もらう）
    '通常の目': 1,          # 通常の目 - 出した分もらう
    
    # 勝ち役
    'ヒフミ': 2,            # 1,2,3 - 2倍払う（即負け）
    'ゾロ目': 3,            # 2,2,2 3,3,3 5,5,5 6,6,6 - 3倍もらう
    'ピンゾロ_win': 5       # 1,1,1（特別扱い） - 5倍もらう
}
    
class ZCurrencyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)
        self.data = self.load_data()
    
    async def setup_hook(self):
        """Botの起動時にスラッシュコマンドを同期"""
        if GUILD_ID:
            # 特定のギルドに同期（即座に反映）
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"スラッシュコマンドがギルド {GUILD_ID} に同期されました（即座反映）")
        else:
            # グローバル同期（反映まで最大1時間）
            await self.tree.sync()
            print("スラッシュコマンドがグローバルに同期されました（反映まで最大1時間）")
    
    def is_admin(self, user_id):
        """管理者かどうかをチェック"""
        return user_id in ADMIN_USER_IDS
    
    async def send_log(self, embed):
        """ログチャンネルにログを送信"""
        print(f"[DEBUG] send_log 呼び出し - LOG_CHANNEL_ID: {LOG_CHANNEL_ID}")
        
        if LOG_CHANNEL_ID:
            try:
                channel = self.get_channel(LOG_CHANNEL_ID)
                print(f"[DEBUG] チャンネル取得結果: {channel}")
                
                if channel:
                    # 権限チェック
                    bot_member = channel.guild.get_member(self.user.id)
                    if bot_member:
                        permissions = channel.permissions_for(bot_member)
                        print(f"[DEBUG] ボットの権限 - 送信: {permissions.send_messages}, 埋め込み: {permissions.embed_links}")
                        
                        if permissions.send_messages and permissions.embed_links:
                            await channel.send(embed=embed)
                            print(f"[SUCCESS] ログをチャンネル {channel.name} (ID: {LOG_CHANNEL_ID}) に送信しました")
                        else:
                            print(f"⚠️ 権限不足 - 送信権限: {permissions.send_messages}, 埋め込み権限: {permissions.embed_links}")
                    else:
                        print("⚠️ ボットがそのサーバーのメンバーではありません")
                else:
                    print(f"⚠️ ログチャンネル（ID: {LOG_CHANNEL_ID}）が見つかりません")
                    # チャンネルが見つからない場合、fetch_channel を試行
                    try:
                        channel = await self.fetch_channel(LOG_CHANNEL_ID)
                        if channel:
                            await channel.send(embed=embed)
                            print(f"[SUCCESS] fetch_channel でログ送信成功: {channel.name}")
                        else:
                            print("⚠️ fetch_channel でもチャンネルが見つかりません")
                    except Exception as fetch_error:
                        print(f"⚠️ fetch_channel エラー: {fetch_error}")
            except Exception as e:
                print(f"⚠️ ログ送信エラー: {e}")
                import traceback
                traceback.print_exc()
        else:
            print("⚠️ LOG_CHANNEL_ID が設定されていません")
    
    def evaluate_chinchin_dice(self, dice):
        """ちんちろのサイコロを評価（表に基づく）"""
        dice_sorted = sorted(dice)
        
        # ピンゾロ（1,1,1）- 特別扱い：5倍もらう
        if dice_sorted == [1, 1, 1]:
            return 'ピンゾロ', 5
        
        # シゴロ（4,5,6）- 即勝ち：2倍もらう
        if dice_sorted == [4, 5, 6]:
            return 'シゴロ', 2
        
        # ゾロ目（2,2,2 3,3,3 4,4,4 5,5,5 6,6,6）- 3倍もらう
        if dice_sorted[0] == dice_sorted[1] == dice_sorted[2]:
            if dice_sorted[0] in [2, 3, 4, 5, 6]:
                return f'{dice_sorted[0]}ゾロ', 3
        
        # ヒフミ（1,2,3）- 即負け：2倍払う
        if dice_sorted == [1, 2, 3]:
            return 'ヒフミ', -2
        
        # 通常の目（ゾロ目が一つある場合）
        # 例：1,1,2 → 2の目, 3,4,4 → 3の目
        if dice_sorted[0] == dice_sorted[1]:
            # 最初の2つが同じ場合、3番目が目
            return f'{dice_sorted[2]}の目', dice_sorted[2]
        elif dice_sorted[1] == dice_sorted[2]:
            # 後ろの2つが同じ場合、1番目が目
            return f'{dice_sorted[0]}の目', dice_sorted[0]
        
        # 役無し
        return '役無し', 0
    
    def load_data(self):
        """データファイルを読み込む"""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {'users': {}, 'transactions': []}
        return {'users': {}, 'transactions': []}
    
    def save_data(self):
        """データファイルに保存（改善版 - バックアップ・原子操作）"""
        try:
            # バックアップを作成
            if os.path.exists(DATA_FILE):
                backup_file = f"{DATA_FILE}.backup"
                shutil.copy2(DATA_FILE, backup_file)
            
            # 一時ファイルに書き込み
            temp_file = f"{DATA_FILE}.tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            
            # 原子的な置換
            if os.path.exists(temp_file):
                os.replace(temp_file, DATA_FILE)
                
        except Exception as e:
            print(f"データ保存エラー: {e}")
            # バックアップから復元を試行
            backup_file = f"{DATA_FILE}.backup"
            if os.path.exists(backup_file):
                try:
                    shutil.copy2(backup_file, DATA_FILE)
                    print("バックアップから復元しました")
                except:
                    print("バックアップからの復元も失敗しました")
    
    def start_auto_save(self):
        """定期的な自動保存を開始"""
        async def auto_save_loop():
            while True:
                try:
                    await asyncio.sleep(300)  # 5分ごとに保存
                    self.save_data()
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] データを自動保存しました")
                except Exception as e:
                    print(f"自動保存エラー: {e}")
        
        # バックグラウンドタスクとして開始
        asyncio.create_task(auto_save_loop())
    
    def get_user_data(self, user_id):
        """ユーザーデータを取得"""
        user_id = str(user_id)
        if user_id not in self.data['users']:
            self.data['users'][user_id] = {
                'balance': INITIAL_BALANCE,
                'total_earned': INITIAL_BALANCE,
                'total_spent': 0,
                'join_date': datetime.now().isoformat()
            }
            self.save_data()
        return self.data['users'][user_id]
    
    def update_balance(self, user_id, amount, transaction_type='other'):
        """残高を更新"""
        user_data = self.get_user_data(user_id)
        user_data['balance'] += amount
        
        if amount > 0:
            user_data['total_earned'] += amount
        else:
            user_data['total_spent'] += abs(amount)
        
        # 取引履歴を記録
        self.data['transactions'].append({
            'user_id': str(user_id),
            'amount': amount,
            'type': transaction_type,
            'timestamp': datetime.now().isoformat()
        })
        
        self.save_data()
        return user_data['balance']
    
    def transfer_currency(self, from_user_id, to_user_id, amount):
        """通貨の送金"""
        from_user = self.get_user_data(from_user_id)
        
        if from_user['balance'] < amount:
            return False, "残高が不足しています"
        
        # 送金処理
        self.update_balance(from_user_id, -amount, 'transfer_out')
        self.update_balance(to_user_id, amount, 'transfer_in')
        
        return True, "送金が完了しました"

bot = ZCurrencyBot()

@bot.event
async def on_ready():
    print(f'{bot.user} がログインしました！')
    print(f'Bot ID: {bot.user.id}')
    print('------')
    
    # ログチャンネルの確認
    if LOG_CHANNEL_ID:
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            print(f"✅ ログチャンネル確認: {log_channel.name} (ID: {LOG_CHANNEL_ID})")
            
            # テストログを送信
            test_embed = discord.Embed(
                title="🤖 ボット起動",
                description="Z通貨Botが正常に起動しました",
                color=0x00ff00,
                timestamp=datetime.now()
            )
            test_embed.add_field(name="ボット名", value=bot.user.display_name, inline=True)
            test_embed.add_field(name="起動時刻", value=datetime.now().strftime('%Y-%m-%d %H:%M:%S'), inline=True)
            
            try:
                await log_channel.send(embed=test_embed)
                print("✅ テストログ送信成功")
            except Exception as e:
                print(f"⚠️ テストログ送信失敗: {e}")
        else:
            print(f"⚠️ ログチャンネル（ID: {LOG_CHANNEL_ID}）が見つかりません")
    else:
        print("⚠️ LOG_CHANNEL_ID が設定されていません")
    
    # 自動保存を開始
    bot.start_auto_save()
    print("定期的な自動保存を開始しました（5分間隔）")

# スラッシュコマンド: 残高確認
@bot.tree.command(name="残高確認", description="残高を確認します（管理者は他ユーザーの残高も確認可能）")
@app_commands.describe(user="確認したいユーザー（管理者のみ）")
async def balance_slash(interaction: discord.Interaction, user: discord.Member = None):
    # 他のユーザーの残高を確認しようとしている場合
    if user and user != interaction.user:
        if not bot.is_admin(interaction.user.id):
            await interaction.response.send_message("❌ 他のユーザーの残高を確認する権限がありません", ephemeral=True)
            return
        target_user = user
    else:
        target_user = interaction.user
    
    user_data = bot.get_user_data(target_user.id)
    
    embed = discord.Embed(
        title=f"💰 {target_user.display_name} の残高",
        color=0x00ff00,
        timestamp=datetime.now()
    )
    embed.add_field(name="現在の残高", value=f"{user_data['balance']:,}Z", inline=True)
    embed.add_field(name="総獲得額", value=f"{user_data['total_earned']:,}Z", inline=True)
    embed.add_field(name="総支出額", value=f"{user_data['total_spent']:,}Z", inline=True)
    embed.set_thumbnail(url=target_user.avatar.url if target_user.avatar else None)
    
    # 管理者が他ユーザーの残高を確認した場合の表示
    if user and user != interaction.user:
        embed.set_footer(text=f"管理者 {interaction.user.display_name} による確認")
    
    await interaction.response.send_message(embed=embed)

# スラッシュコマンド: 発行
@bot.tree.command(name="発行", description="管理者専用：指定ユーザーに通貨を発行")
@app_commands.describe(user="発行対象のユーザー", amount="発行する金額")
async def issue_slash(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not bot.is_admin(interaction.user.id):
        await interaction.response.send_message("❌ この機能を使用する権限がありません", ephemeral=True)
        return
    
    if amount <= 0:
        await interaction.response.send_message("❌ 発行額は1以上である必要があります", ephemeral=True)
        return
    
    new_balance = bot.update_balance(user.id, amount, 'admin_issue')
    
    embed = discord.Embed(
        title="🏦 通貨発行",
        description=f"{user.mention} に {amount:,}Z を発行しました",
        color=0x0099ff,
        timestamp=datetime.now()
    )
    embed.add_field(name="発行額", value=f"{amount:,}Z", inline=True)
    embed.add_field(name="新しい残高", value=f"{new_balance:,}Z", inline=True)
    embed.set_footer(text=f"管理者: {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed)
    
    # ログチャンネルにも送信
    log_embed = discord.Embed(
        title="📈 通貨発行ログ",
        description=f"管理者が通貨を発行しました",
        color=0x0099ff,
        timestamp=datetime.now()
    )
    log_embed.add_field(name="管理者", value=f"{interaction.user.mention} ({interaction.user.display_name})", inline=True)
    log_embed.add_field(name="対象ユーザー", value=f"{user.mention} ({user.display_name})", inline=True)
    log_embed.add_field(name="発行額", value=f"{amount:,}Z", inline=True)
    log_embed.add_field(name="新しい残高", value=f"{new_balance:,}Z", inline=True)
    log_embed.add_field(name="実行チャンネル", value=f"{interaction.channel.mention}", inline=True)
    log_embed.add_field(name="ユーザーID", value=f"`{user.id}`", inline=True)
    await bot.send_log(log_embed)

# スラッシュコマンド: 減少
@bot.tree.command(name="減少", description="管理者専用：指定ユーザーの通貨を減少")
@app_commands.describe(user="減少対象のユーザー", amount="減少する金額")
async def reduce_slash(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not bot.is_admin(interaction.user.id):
        await interaction.response.send_message("❌ この機能を使用する権限がありません", ephemeral=True)
        return
    
    if amount <= 0:
        await interaction.response.send_message("❌ 減少額は1以上である必要があります", ephemeral=True)
        return
    
    user_data = bot.get_user_data(user.id)
    if user_data['balance'] < amount:
        await interaction.response.send_message(f"❌ {user.display_name} の残高が不足しています（現在: {user_data['balance']:,}Z）", ephemeral=True)
        return
    
    new_balance = bot.update_balance(user.id, -amount, 'admin_reduce')
    
    embed = discord.Embed(
        title="🏦 通貨減少",
        description=f"{user.mention} から {amount:,}Z を減少させました",
        color=0xff9900,
        timestamp=datetime.now()
    )
    embed.add_field(name="減少額", value=f"{amount:,}Z", inline=True)
    embed.add_field(name="新しい残高", value=f"{new_balance:,}Z", inline=True)
    embed.set_footer(text=f"管理者: {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed)
    
    # ログチャンネルにも送信
    log_embed = discord.Embed(
        title="📉 通貨減少ログ",
        description=f"管理者が通貨を減少させました",
        color=0xff9900,
        timestamp=datetime.now()
    )
    log_embed.add_field(name="管理者", value=f"{interaction.user.mention} ({interaction.user.display_name})", inline=True)
    log_embed.add_field(name="対象ユーザー", value=f"{user.mention} ({user.display_name})", inline=True)
    log_embed.add_field(name="減少額", value=f"{amount:,}Z", inline=True)
    log_embed.add_field(name="新しい残高", value=f"{new_balance:,}Z", inline=True)
    log_embed.add_field(name="実行チャンネル", value=f"{interaction.channel.mention}", inline=True)
    log_embed.add_field(name="ユーザーID", value=f"`{user.id}`", inline=True)
    await bot.send_log(log_embed)

# スラッシュコマンド: ロール発行
@bot.tree.command(name="ロール発行", description="管理者専用：指定ロールのメンバー全員に通貨を発行")
@app_commands.describe(role="発行対象のロール", amount="発行する金額（一人当たり）")
async def role_issue_slash(interaction: discord.Interaction, role: discord.Role, amount: int):
    if not bot.is_admin(interaction.user.id):
        await interaction.response.send_message("❌ この機能を使用する権限がありません", ephemeral=True)
        return
    
    if amount <= 0:
        await interaction.response.send_message("❌ 発行額は1以上である必要があります", ephemeral=True)
        return
    
    members = role.members
    if not members:
        await interaction.response.send_message(f"❌ ロール {role.name} にメンバーがいません", ephemeral=True)
        return
    
    # 発行処理
    issued_count = 0
    for member in members:
        if not member.bot:  # ボットには発行しない
            bot.update_balance(member.id, amount, 'role_issue')
            issued_count += 1
    
    embed = discord.Embed(
        title="👥 ロール一括発行",
        description=f"ロール {role.name} のメンバーに通貨を発行しました",
        color=0x9932cc,
        timestamp=datetime.now()
    )
    embed.add_field(name="対象ロール", value=role.name, inline=True)
    embed.add_field(name="発行額（一人当たり）", value=f"{amount:,}Z", inline=True)
    embed.add_field(name="対象メンバー数", value=f"{issued_count}人", inline=True)
    embed.add_field(name="総発行額", value=f"{amount * issued_count:,}Z", inline=True)
    embed.set_footer(text=f"管理者: {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed)
    
    # ログチャンネルにも送信
    log_embed = discord.Embed(
        title="👥 ロール一括発行ログ",
        description=f"管理者がロールメンバーに一括発行しました",
        color=0x9932cc,
        timestamp=datetime.now()
    )
    log_embed.add_field(name="管理者", value=f"{interaction.user.mention} ({interaction.user.display_name})", inline=True)
    log_embed.add_field(name="対象ロール", value=f"{role.mention} ({role.name})", inline=True)
    log_embed.add_field(name="発行額（一人当たり）", value=f"{amount:,}Z", inline=True)
    log_embed.add_field(name="対象メンバー数", value=f"{issued_count}人", inline=True)
    log_embed.add_field(name="総発行額", value=f"{amount * issued_count:,}Z", inline=True)
    log_embed.add_field(name="実行チャンネル", value=f"{interaction.channel.mention}", inline=True)
    
    # 対象メンバーリスト（最大10人まで表示）
    member_list = [f"<@{member.id}>" for member in members[:10] if not member.bot]
    if len(member_list) > 0:
        member_text = ", ".join(member_list)
        if issued_count > 10:
            member_text += f"\n...他{issued_count - 10}人"
        log_embed.add_field(name="対象メンバー", value=member_text, inline=False)
    
    await bot.send_log(log_embed)

# スラッシュコマンド: 送金
@bot.tree.command(name="送金", description="他のユーザーに送金")
@app_commands.describe(user="送金先のユーザー", amount="送金する金額")
async def send_slash(interaction: discord.Interaction, user: discord.Member, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ 送金額は1以上である必要があります", ephemeral=True)
        return
    
    if user == interaction.user:
        await interaction.response.send_message("❌ 自分自身には送金できません", ephemeral=True)
        return
    
    if user.bot:
        await interaction.response.send_message("❌ ボットには送金できません", ephemeral=True)
        return
    
    success, message = bot.transfer_currency(interaction.user.id, user.id, amount)
    
    if success:
        embed = discord.Embed(
            title="✅ 送金完了",
            description=f"{interaction.user.mention} が {user.mention} に {amount:,}Z を送金しました",
            color=0x00ff00,
            timestamp=datetime.now()
        )
        await interaction.response.send_message(embed=embed)
        
        # ログチャンネルにも送信
        log_embed = discord.Embed(
            title="💸 送金ログ",
            description=f"ユーザー間で送金が行われました",
            color=0x00ff00,
            timestamp=datetime.now()
        )
        log_embed.add_field(name="送金者", value=f"{interaction.user.mention} ({interaction.user.display_name})", inline=True)
        log_embed.add_field(name="受取者", value=f"{user.mention} ({user.display_name})", inline=True)
        log_embed.add_field(name="送金額", value=f"{amount:,}Z", inline=True)
        log_embed.add_field(name="実行チャンネル", value=f"{interaction.channel.mention}", inline=True)
        log_embed.add_field(name="送金者ID", value=f"`{interaction.user.id}`", inline=True)
        log_embed.add_field(name="受取者ID", value=f"`{user.id}`", inline=True)
        
        # 残高情報も追加
        sender_data = bot.get_user_data(interaction.user.id)
        receiver_data = bot.get_user_data(user.id)
        log_embed.add_field(name="送金者の新残高", value=f"{sender_data['balance']:,}Z", inline=True)
        log_embed.add_field(name="受取者の新残高", value=f"{receiver_data['balance']:,}Z", inline=True)
        log_embed.add_field(name="　", value="　", inline=True)  # 空白調整
        
        await bot.send_log(log_embed)
    else:
        await interaction.response.send_message(f"❌ {message}", ephemeral=True)


# スラッシュコマンド: ちんちろ
@bot.tree.command(name="ちんちろ", description="通貨を賭けてサイコロバトル")
async def chinchin_slash(interaction: discord.Interaction):
    user_data = bot.get_user_data(interaction.user.id)
    
    # レート選択用のView
    class ChinchinRateView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
        
        @discord.ui.button(label="1,000Z", style=discord.ButtonStyle.primary, emoji="🎲")
        async def rate_1000(self, interaction: discord.Interaction, button: discord.ui.Button):
            await self.start_chinchin(interaction, 1000)
        
        @discord.ui.button(label="5,000Z", style=discord.ButtonStyle.success, emoji="🎲")
        async def rate_5000(self, interaction: discord.Interaction, button: discord.ui.Button):
            await self.start_chinchin(interaction, 5000)
        
        @discord.ui.button(label="10,000Z", style=discord.ButtonStyle.danger, emoji="🎲")
        async def rate_10000(self, interaction: discord.Interaction, button: discord.ui.Button):
            await self.start_chinchin(interaction, 10000)
        
        @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary, emoji="❌")
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            embed = discord.Embed(
                title="❌ ちんちろをキャンセルしました",
                color=0xff0000,
                timestamp=datetime.now()
            )
            await interaction.response.edit_message(embed=embed, view=None)
        
        async def start_chinchin(self, interaction: discord.Interaction, amount: int):
            user_data = bot.get_user_data(interaction.user.id)
            if user_data['balance'] < amount:
                await interaction.response.edit_message(
                    embed=discord.Embed(
                        title="❌ 残高不足",
                        description=f"賭け金{amount:,}Zに対して残高が不足しています\n現在の残高: {user_data['balance']:,}Z",
                        color=0xff0000,
                        timestamp=datetime.now()
                    ),
                    view=None
                )
                return
            
            await play_chinchin_game(interaction, amount)
        
        async def on_timeout(self):
            # タイムアウト時の処理
            for item in self.children:
                item.disabled = True
    
    # レート選択画面を表示
    embed = discord.Embed(
        title="🎲 ちんちろバトル",
        description=f"{interaction.user.mention} さん、賭け金を選択してください",
        color=0xff6600,
        timestamp=datetime.now()
    )
    embed.add_field(name="現在の残高", value=f"{user_data['balance']:,}Z", inline=True)
    embed.add_field(name="選択可能なレート", value="1,000Z / 5,000Z / 10,000Z", inline=False)
    
    view = ChinchinRateView()
    await interaction.response.send_message(embed=embed, view=view)

# ちんちろゲーム本体の処理
async def play_chinchin_game(interaction: discord.Interaction, amount: int):
    global bot  # botインスタンスをグローバルに使用
    
    # メッセージ更新のヘルパー関数
    async def safe_edit_message(embed, view=None):
        try:
            await interaction.edit_original_response(embed=embed, view=view)
        except discord.NotFound:
            # メッセージが見つからない場合はfollowupを使用
            try:
                await interaction.followup.send(embed=embed, view=view)
            except:
                pass  # 失敗した場合は無視
        except Exception as e:
            print(f"メッセージ更新エラー: {e}")
    
    # バトル開始の演出
    embed = discord.Embed(
        title="🎲✨ ちんちろバトル開始！ ✨🎲",
        description=f"**{interaction.user.mention}** が **{amount:,}Z** を賭けて熱いバトルに挑戦！\n🔥 運命のサイコロが回り始める... 🔥",
        color=0xff6600,
        timestamp=datetime.now()
    )
    embed.add_field(name="💰 賭け金", value=f"**{amount:,}Z**", inline=True)
    embed.add_field(name="📋 ルール", value="最大3回までサイコロを振れます\n役が出るまで挑戦しよう！", inline=True)
    embed.add_field(name="🎯 目標", value="相手より強い役を出せ！", inline=True)
    
    # インタラクションが既に応答済みかどうかをチェック
    if interaction.response.is_done():
        await safe_edit_message(embed, view=None)
    else:
        await interaction.response.edit_message(embed=embed, view=None)
    await asyncio.sleep(4)
    
    # プレイヤーのターン開始
    embed = discord.Embed(
        title="🎲 あなたのターン開始！",
        description="🌟 **運命のサイコロを振ろう！** 🌟",
        color=0x00ff00,
        timestamp=datetime.now()
    )
    embed.add_field(name="💰 賭け金", value=f"{amount:,}Z", inline=True)
    embed.add_field(name="👤 挑戦者", value=interaction.user.display_name, inline=True)
    embed.add_field(name="🎯 状況", value="最初の挑戦！", inline=True)
    
    await safe_edit_message(embed)
    await asyncio.sleep(3)
    
    # プレイヤーのターン
    player_hand = None
    player_power = 0
    player_dice_history = []
    player_results = []
    
    for attempt in range(3):
        # サイコロを振る演出
        embed = discord.Embed(
            title=f"🎲 第{attempt + 1}投目 🎲",
            description="🌀 **サイコロが転がっています...** 🌀",
            color=0x00ff00,
            timestamp=datetime.now()
        )
        embed.add_field(name="💰 賭け金", value=f"{amount:,}Z", inline=True)
        embed.add_field(name="🔄 投目", value=f"{attempt + 1}/3回目", inline=True)
        embed.add_field(name="⏳ 状況", value="運命を決める瞬間...", inline=True)
        
        # 過去の結果を表示
        if player_results:
            history_text = "\n".join([f"第{i+1}投: {result}" for i, result in enumerate(player_results)])
            embed.add_field(name="📊 これまでの結果", value=history_text, inline=False)
        
        await safe_edit_message(embed)
        await asyncio.sleep(3)
        
        # サイコロの結果
        dice = [random.randint(1, 6) for _ in range(3)]
        player_dice_history.append(dice)
        hand, power = bot.evaluate_chinchin_dice(dice)
        
        # サイコロの絵文字表示
        dice_emojis = ['⚀', '⚁', '⚂', '⚃', '⚄', '⚅']
        dice_display = ' '.join([dice_emojis[d-1] for d in dice])
        
        # 結果を記録
        player_results.append(f"{dice_display} → **{hand}**")
        
        # 結果表示
        embed = discord.Embed(
            title=f"🎲 第{attempt + 1}投目の結果！ 🎲",
            description=f"**{dice_display}**\n({dice[0]}, {dice[1]}, {dice[2]})",
            color=0x00ff00,
            timestamp=datetime.now()
        )
        
        # 役の結果に応じて色とメッセージを変更
        if hand == 'ピンゾロ':
            embed.color = 0xffd700
            embed.add_field(name="🏆 結果", value=f"**{hand}** ⭐最強役！⭐", inline=False)
        elif 'シゴロ' in hand:
            embed.color = 0xff69b4
            embed.add_field(name="🎉 結果", value=f"**{hand}** 🔥即勝ち役！🔥", inline=False)
        elif 'ゾロ' in hand:
            embed.color = 0x9932cc
            embed.add_field(name="✨ 結果", value=f"**{hand}** 💎強力な役！💎", inline=False)
        elif '目' in hand:
            embed.color = 0x32cd32
            embed.add_field(name="⭐ 結果", value=f"**{hand}** 📈役が出た！📈", inline=False)
        elif hand == 'ヒフミ':
            embed.color = 0x8b0000
            embed.add_field(name="💀 結果", value=f"**{hand}** ⚡即負け役...⚡", inline=False)
        else:
            embed.color = 0x696969
            embed.add_field(name="😐 結果", value=f"**{hand}** 💨まだ役なし💨", inline=False)
        
        # これまでの全結果を表示
        all_results = "\n".join([f"第{i+1}投: {result}" for i, result in enumerate(player_results)])
        embed.add_field(name="📊 あなたの全結果", value=all_results, inline=False)
        
        # 役が出た場合は終了
        if hand == 'ヒフミ' or '目' in hand or hand == 'ピンゾロ' or 'シゴロ' in hand or (hand not in ['役無し'] and power != 0):
            player_hand = hand
            player_power = power
            
            if hand == 'ヒフミ':
                embed.add_field(name="⚡ 次の展開", value="即負け役が出ました！\n🤖 **Botのターンへ！**", inline=False)
            elif 'シゴロ' in hand:
                embed.add_field(name="🔥 次の展開", value="シゴロ！即勝ち役です！\n🤖 **Botのターンで逆転なるか？**", inline=False)
            elif hand == 'ピンゾロ':
                embed.add_field(name="👑 次の展開", value="最強役ピンゾロ！\n🤖 **Botに勝ち目はあるのか？**", inline=False)
            else:
                embed.add_field(name="✨ 次の展開", value="役が確定しました！\n🤖 **Botの反撃が始まる！**", inline=False)
            
            await safe_edit_message(embed)
            await asyncio.sleep(4)
            break
        else:
            if attempt < 2:
                embed.add_field(name="🔄 次の展開", value=f"役なし...まだ**{2-attempt}回**チャンスがあります！\n⏳ **次の投げで運命が決まる！**", inline=False)
                await safe_edit_message(embed)
                await asyncio.sleep(4)
            else:
                player_hand = hand
                player_power = power
                embed.add_field(name="😓 結果", value="3回振っても役なし...\n🤖 **Botのターンです！**", inline=False)
                await safe_edit_message(embed)
                await asyncio.sleep(4)
    
    # Botのターン開始演出
    embed = discord.Embed(
        title="🤖✨ Botのターン開始！ ✨🤖",
        description="🔥 **AIが反撃開始！** 🔥\n⚡ 人工知能の運命やいかに... ⚡",
        color=0xff4500,
        timestamp=datetime.now()
    )
    embed.add_field(name="👤 あなたの最終結果", value=f"**{player_hand}**\n🎲 {' '.join([['⚀', '⚁', '⚂', '⚃', '⚄', '⚅'][d-1] for d in player_dice_history[-1]])}", inline=False)
    embed.add_field(name="🎯 Botの目標", value="あなたの役を上回れ！", inline=True)
    embed.add_field(name="⚔️ 戦況", value="激戦必至！", inline=True)
    
    await safe_edit_message(embed)
    await asyncio.sleep(4)
    
    # Botのターン
    bot_hand = None
    bot_power = 0
    bot_dice_history = []
    bot_results = []
    
    for attempt in range(3):
        # サイコロを振る演出
        embed = discord.Embed(
            title=f"🤖 Bot 第{attempt + 1}投目 🤖",
            description="⚙️ **AIが計算中...サイコロが回転！** ⚙️",
            color=0xff4500,
            timestamp=datetime.now()
        )
        
        # プレイヤーの結果を常に表示
        embed.add_field(name="👤 あなたの最終結果", value=f"**{player_hand}**", inline=True)
        embed.add_field(name="🤖 Bot投目", value=f"{attempt + 1}/3回目", inline=True)
        embed.add_field(name="⏳ 状況", value="AIの運命を決める瞬間...", inline=True)
        
        # Botの過去の結果を表示
        if bot_results:
            bot_history = "\n".join([f"第{i+1}投: {result}" for i, result in enumerate(bot_results)])
            embed.add_field(name="🤖 Botのこれまでの結果", value=bot_history, inline=False)
        
        await safe_edit_message(embed)
        await asyncio.sleep(3)
        
        # サイコロの結果
        dice = [random.randint(1, 6) for _ in range(3)]
        bot_dice_history.append(dice)
        hand, power = bot.evaluate_chinchin_dice(dice)
        
        # サイコロの絵文字表示
        dice_emojis = ['⚀', '⚁', '⚂', '⚃', '⚄', '⚅']
        dice_display = ' '.join([dice_emojis[d-1] for d in dice])
        
        # 結果を記録
        bot_results.append(f"{dice_display} → **{hand}**")
        
        # 結果表示
        embed = discord.Embed(
            title=f"🤖 Bot 第{attempt + 1}投目の結果！ 🤖",
            description=f"**{dice_display}**\n({dice[0]}, {dice[1]}, {dice[2]})",
            color=0xff4500,
            timestamp=datetime.now()
        )
        
        # プレイヤーの結果を比較表示
        player_dice_display = ' '.join([['⚀', '⚁', '⚂', '⚃', '⚄', '⚅'][d-1] for d in player_dice_history[-1]])
        embed.add_field(name="👤 あなたの結果", value=f"**{player_hand}**\n{player_dice_display}", inline=True)
        
        # Botの役の結果に応じて色とメッセージを変更
        if hand == 'ピンゾロ':
            embed.color = 0xffd700
            embed.add_field(name="🏆 Bot結果", value=f"**{hand}** ⭐最強役！⭐", inline=True)
        elif 'シゴロ' in hand:
            embed.color = 0xff69b4
            embed.add_field(name="🎉 Bot結果", value=f"**{hand}** 🔥即勝ち役！🔥", inline=True)
        elif 'ゾロ' in hand:
            embed.color = 0x9932cc
            embed.add_field(name="✨ Bot結果", value=f"**{hand}** 💎強力な役！💎", inline=True)
        elif '目' in hand:
            embed.color = 0x32cd32
            embed.add_field(name="⭐ Bot結果", value=f"**{hand}** 📈役が出た！📈", inline=True)
        elif hand == 'ヒフミ':
            embed.color = 0x8b0000
            embed.add_field(name="💀 Bot結果", value=f"**{hand}** ⚡即負け役...⚡", inline=True)
        else:
            embed.color = 0x696969
            embed.add_field(name="😐 Bot結果", value=f"**{hand}** 💨まだ役なし💨", inline=True)
        
        # 空白調整
        embed.add_field(name="　", value="　", inline=True)
        
        # Botの全結果を表示
        all_bot_results = "\n".join([f"第{i+1}投: {result}" for i, result in enumerate(bot_results)])
        embed.add_field(name="🤖 Botの全結果", value=all_bot_results, inline=False)
        
        # 役が出た場合は終了
        if hand == 'ヒフミ' or '目' in hand or hand == 'ピンゾロ' or 'シゴロ' in hand or (hand not in ['役無し'] and power != 0):
            bot_hand = hand
            bot_power = power
            
            if hand == 'ヒフミ':
                embed.add_field(name="⚡ 展開", value="Botが即負け役を出しました！\n🎊 **勝敗判定へ！**", inline=False)
            elif 'シゴロ' in hand:
                embed.add_field(name="🔥 展開", value="Botがシゴロを出しました！\n⚔️ **最終決戦！**", inline=False)
            elif hand == 'ピンゾロ':
                embed.add_field(name="👑 展開", value="Botが最強役を出しました！\n💥 **究極の対決！**", inline=False)
            else:
                embed.add_field(name="✨ 展開", value="Botも役が確定！\n🎭 **運命の判定タイム！**", inline=False)
            
            await safe_edit_message(embed)
            await asyncio.sleep(4)
            break
        else:
            if attempt < 2:
                embed.add_field(name="🔄 展開", value=f"Botも役なし...まだ**{2-attempt}回**残っています！\n🎲 **AIの逆転なるか？**", inline=False)
                await safe_edit_message(embed)
                await asyncio.sleep(4)
            else:
                bot_hand = hand
                bot_power = power
                embed.add_field(name="😓 結果", value="Botも3回振って役なし...\n🎊 **ついに勝敗判定！**", inline=False)
                await safe_edit_message(embed)
                await asyncio.sleep(4)
    
    # 勝敗判定の演出
    embed = discord.Embed(
        title="⚡ 運命の判定タイム ⚡",
        description="🎭 **ドキドキの結果発表！** 🎭\n✨ 勝敗を決める瞬間です... ✨",
        color=0xffff00,
        timestamp=datetime.now()
    )
    
    # 両者の最終結果を美しく表示
    player_final_dice = ' '.join([['⚀', '⚁', '⚂', '⚃', '⚄', '⚅'][d-1] for d in player_dice_history[-1]])
    bot_final_dice = ' '.join([['⚀', '⚁', '⚂', '⚃', '⚄', '⚅'][d-1] for d in bot_dice_history[-1]])
    
    embed.add_field(name="👤 あなたの最終結果", value=f"**{player_hand}**\n{player_final_dice}", inline=True)
    embed.add_field(name="🆚", value="**VS**", inline=True)
    embed.add_field(name="🤖 Botの最終結果", value=f"**{bot_hand}**\n{bot_final_dice}", inline=True)
    embed.add_field(name="💰 賭け金", value=f"{amount:,}Z", inline=True)
    embed.add_field(name="⏳ 状況", value="判定中...", inline=True)
    embed.add_field(name="🎲 緊張", value="MAX!", inline=True)
    
    await safe_edit_message(embed)
    await asyncio.sleep(5)
    
    await asyncio.sleep(4)
    
    # 勝敗判定（表に基づく）
    player_is_instant_lose = player_hand == 'ヒフミ'
    bot_is_instant_lose = bot_hand == 'ヒフミ'
    player_is_shigoro = 'シゴロ' in player_hand
    bot_is_shigoro = 'シゴロ' in bot_hand
    
    if player_is_instant_lose and bot_is_instant_lose:
        # 両方即負け → 引き分け
        result = "引き分け"
        winnings = 0
        color = 0xffff00
        result_emoji = "🤝"
    elif player_is_instant_lose:
        # プレイヤーのみ即負け → 敗北
        result = "敗北"
        winnings = -amount * 2  # ヒフミは2倍払う
        color = 0xff0000
        result_emoji = "😢"
    elif bot_is_instant_lose:
        # Botのみ即負け → 勝利
        result = "勝利"
        winnings = amount * 2  # ヒフミは2倍もらう
        color = 0x00ff00
        result_emoji = "🎉"
    elif player_is_shigoro and bot_is_shigoro:
        # 両方シゴロ → 引き分け
        result = "引き分け"
        winnings = 0
        color = 0xffff00
        result_emoji = "🤝"
    elif player_is_shigoro:
        # プレイヤーのみシゴロ → 勝利
        result = "勝利"
        winnings = amount * 2  # シゴロは2倍もらう
        color = 0x00ff00
        result_emoji = "🎉"
    elif bot_is_shigoro:
        # Botのみシゴロ → 敗北
        result = "敗北"
        winnings = -amount * 2  # シゴロは2倍払う
        color = 0xff0000
        result_emoji = "😢"
    else:
        # 通常の勝負（役の強さで比較）
        if player_hand == 'ピンゾロ' and bot_hand != 'ピンゾロ':
            # プレイヤーがピンゾロ → 5倍もらう
            result = "勝利"
            winnings = amount * 5
            color = 0xffd700
            result_emoji = "🏆"
        elif bot_hand == 'ピンゾロ' and player_hand != 'ピンゾロ':
            # Botがピンゾロ → 5倍払う
            result = "敗北"
            winnings = -amount * 5
            color = 0xff0000
            result_emoji = "😱"
        elif '目' in player_hand and '目' in bot_hand:
            # 両方通常の目 → 目の数で比較
            player_num = int(player_hand[0])
            bot_num = int(bot_hand[0])
            if player_num > bot_num:
                result = "勝利"
                winnings = amount
                color = 0x00ff00
                result_emoji = "🎉"
            elif player_num < bot_num:
                result = "敗北"
                winnings = -amount
                color = 0xff0000
                result_emoji = "😢"
            else:
                result = "引き分け"
                winnings = 0
                color = 0xffff00
                result_emoji = "🤝"
        elif '目' in player_hand and player_hand != '役無し':
            # プレイヤーに目があり、Botが役無し
            result = "勝利"
            winnings = amount
            color = 0x00ff00
            result_emoji = "🎉"
        elif '目' in bot_hand and bot_hand != '役無し':
            # Botに目があり、プレイヤーが役無し
            result = "敗北"
            winnings = -amount
            color = 0xff0000
            result_emoji = "😢"
        elif 'ゾロ' in player_hand and 'ゾロ' not in bot_hand:
            # プレイヤーのみゾロ目 → 3倍もらう
            result = "勝利"
            winnings = amount * 3
            color = 0x00ff00
            result_emoji = "🎉"
        elif 'ゾロ' in bot_hand and 'ゾロ' not in player_hand:
            # Botのみゾロ目 → 3倍払う
            result = "敗北"
            winnings = -amount * 3
            color = 0xff0000
            result_emoji = "😢"
        else:
            # 両方役無し → 引き分け
            result = "引き分け"
            winnings = 0
            color = 0xffff00
            result_emoji = "🤝"
    
    # 残高更新
    new_balance = bot.update_balance(interaction.user.id, winnings, 'chinchin')
    
    # 結果表示
    embed = discord.Embed(
        title=f"{result_emoji} 🎊 ちんちろバトル結果発表！ 🎊 {result_emoji}",
        description=f"🎭 **{result}** 🎭\n✨ 運命の戦いが決着しました！ ✨",
        color=color,
        timestamp=datetime.now()
    )
    
    # 勝敗結果を大きく表示
    if result == "勝利":
        embed.add_field(name="🏆 結果", value=f"**🎉 {result} 🎉**", inline=False)
    elif result == "敗北":
        embed.add_field(name="💔 結果", value=f"**😢 {result} 😢**", inline=False)
    else:
        embed.add_field(name="🤝 結果", value=f"**🤝 {result} 🤝**", inline=False)
    
    # 詳細結果
    player_final_dice = ' '.join([['⚀', '⚁', '⚂', '⚃', '⚄', '⚅'][d-1] for d in player_dice_history[-1]])
    bot_final_dice = ' '.join([['⚀', '⚁', '⚂', '⚃', '⚄', '⚅'][d-1] for d in bot_dice_history[-1]])
    
    embed.add_field(name="👤 あなたの役", value=f"**{player_hand}**\n{player_final_dice}", inline=True)
    embed.add_field(name="🤖 Botの役", value=f"**{bot_hand}**\n{bot_final_dice}", inline=True)
    
    # 勝敗による絵文字
    if result == "勝利":
        embed.add_field(name="⚔️ 勝敗", value="🏆 **勝利！** 🏆", inline=True)
    elif result == "敗北":
        embed.add_field(name="⚔️ 勝敗", value="💀 **敗北...** 💀", inline=True)
    else:
        embed.add_field(name="⚔️ 勝敗", value="🤝 **引き分け** 🤝", inline=True)
    
    embed.add_field(name="💰 賭け金", value=f"{amount:,}Z", inline=True)
    
    # 獲得/損失の表示
    if winnings > 0:
        embed.add_field(name="💎 獲得", value=f"**+{winnings:,}Z** 🎉", inline=True)
    elif winnings < 0:
        embed.add_field(name="💸 損失", value=f"**{winnings:,}Z** 😢", inline=True)
    else:
        embed.add_field(name="💫 増減", value="**±0Z** 🤝", inline=True)
    
    embed.add_field(name="🏦 現在の残高", value=f"**{new_balance:,}Z**", inline=True)
    
    # 配当説明
    if abs(winnings) > amount:
        multiplier = abs(winnings) // amount
        if multiplier >= 5:
            embed.add_field(name="🏆 配当", value=f"**{multiplier}倍** ⭐超大当たり⭐", inline=False)
        elif multiplier >= 3:
            embed.add_field(name="✨ 配当", value=f"**{multiplier}倍** 💎大当たり💎", inline=False)
        else:
            embed.add_field(name="🎉 配当", value=f"**{multiplier}倍** 🎊当たり🎊", inline=False)
    
    # 特別メッセージ
    if result == "勝利":
        if winnings >= amount * 5:
            embed.add_field(name="🌟 特別メッセージ", value="🎆 **伝説級の大勝利！** 🎆\n✨ あなたは真のちんちろマスター！ ✨", inline=False)
        elif winnings >= amount * 3:
            embed.add_field(name="🎉 特別メッセージ", value="🔥 **素晴らしい勝利！** 🔥\n⭐ 運が味方についています！ ⭐", inline=False)
        else:
            embed.add_field(name="😊 特別メッセージ", value="🎊 **ナイス勝利！** 🎊\n👍 調子が良いですね！ 👍", inline=False)
    elif result == "敗北":
        embed.add_field(name="💪 特別メッセージ", value="😤 **次こそリベンジ！** 😤\n🔥 諦めずに挑戦しよう！ 🔥", inline=False)
    else:
        embed.add_field(name="🤝 特別メッセージ", value="⚡ **互角の戦い！** ⚡\n🎲 次の勝負で決着をつけよう！ 🎲", inline=False)
    
    embed.set_author(name=f"🎲 {interaction.user.display_name} のちんちろバトル", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
    embed.set_footer(text="🎊 また挑戦してね！次回も熱い戦いを期待しています 🎊")
    await safe_edit_message(embed)

# スラッシュコマンド: ヘルプ
@bot.tree.command(name="ヘルプ", description="Z通貨Botの使い方を表示")
async def help_slash(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Z通貨Bot ヘルプ",
        description="Z通貨を使った様々な機能があります！",
        color=0x0099ff,
        timestamp=datetime.now()
    )
    
    # 一般ユーザー向けコマンド
    user_commands = """
    `/残高確認` - 自分の残高を確認
    `/送金 <ユーザー> <金額>` - 他のユーザーに送金
    `/ちんちろ <金額>` - ちんちろバトルで勝負
    """
    
    embed.add_field(name="📋 一般コマンド", value=user_commands, inline=False)
    
    # 管理者向けコマンド
    if bot.is_admin(interaction.user.id):
        admin_commands = """
        `/残高確認 <ユーザー>` - 他ユーザーの残高確認
        `/発行 <ユーザー> <金額>` - 通貨を発行
        `/減少 <ユーザー> <金額>` - 通貨を減少
        `/ロール発行 <ロール> <金額>` - ロール一括発行
        """
        embed.add_field(name="🛡️ 管理者専用コマンド", value=admin_commands, inline=False)
    
    # ちんちろの役説明
    chinchin_info = """
    **ちんちろの配当:**
    • ピンゾロ(1,1,1): 5倍もらう
    • シゴロ(4,5,6): 2倍もらう（即勝ち）
    • ゾロ目(2,2,2 3,3,3 4,4,4 5,5,5 6,6,6): 3倍もらう
    • 通常の目: 出した分もらう
    • 役無し: 出した分払う
    • ヒフミ(1,2,3): 2倍払う（即負け）
    """
    embed.add_field(name="🎲 ちんちろについて", value=chinchin_info, inline=False)
    
    embed.add_field(name="💰 初期残高", value=f"{INITIAL_BALANCE:,}Z", inline=True)
    
    await interaction.response.send_message(embed=embed)

# エラーハンドリング（スラッシュコマンド用）
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ この機能を使用する権限がありません", ephemeral=True)
    elif isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(f"❌ コマンドはクールダウン中です。{error.retry_after:.1f}秒後に再試行してください", ephemeral=True)
    else:
        print(f"予期しないエラー: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ 予期しないエラーが発生しました", ephemeral=True)

if __name__ == "__main__":
    # Botトークンを.envファイルから読み込み
    TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
    
    print("🤖 Z通貨Bot - 設定確認")
    print("=" * 50)
    print(f"管理者数: {len(ADMIN_USER_IDS)}人")
    if ADMIN_USER_IDS:
        print(f"管理者ID: {ADMIN_USER_IDS}")
    print(f"ギルドID: {GUILD_ID}")
    print(f"ログチャンネルID: {LOG_CHANNEL_ID}")
    print("=" * 50)
    
    if TOKEN == "YOUR_BOT_TOKEN_HERE" or not TOKEN:
        print("⚠️  Z通貨Bot - 設定が必要です！")
        print("=" * 50)
        print("1. .envファイルを編集してください")
        print("2. BOT_TOKEN=あなたのBotトークン")
        print("3. ADMIN_USER_IDS=管理者のDiscordユーザーID（カンマ区切り）")
        print("4. LOG_CHANNEL_ID=ログ送信先のチャンネルID")
        print("=" * 50)
        print("管理者IDの確認方法:")
        print("- Discord の開発者モードを有効にする")
        print("- ユーザーを右クリック → 'IDをコピー' を選択")
        print("=" * 50)
    else:
        print("🤖 Z通貨Bot 起動中...")
        bot.run(TOKEN)
