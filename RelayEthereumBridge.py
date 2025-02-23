import random
import time
from typing import Tuple
from loguru import logger
from config import config, Chains
from core.bot import Bot
from core.onchain import Onchain
from models.account import Account
from models.chain import Chain
from utils.inputs import input_deposit_amount, input_pause
from utils.logging import init_logger
from utils.utils import (random_sleep, get_accounts, select_profiles)
import re

def input_withdraw_chain() -> Tuple[Chain, str]:

    input_chain_message = (
        f"Выбор сети вывода с каждого кошелька токена ЕТН для пополнения сети ETHEREUM:\n"
        f"1 - ARBITRUM ONE\n"
        f"2 - BASE\n"
        f"3 - OPTIMISM\n"
    )
    while True:
        input_chain = input(f'{input_chain_message}Введите номер выбора и нажмите ENTER: ')
        input_chain = re.sub(r'\D', '', input_chain)

        if input_chain == '1':
            chain = Chains.ARBITRUM_ONE
            return chain, input_chain

        if input_chain == '2':
            chain = Chains.BASE
            return chain, input_chain

        if input_chain == '3':
            chain = Chains.OP
            return chain, input_chain

        print("Некорректный ввод! Введите 1, 2 или 3.\n")

def input_erc_deposit() -> Tuple:

    chain, input_chain = input_withdraw_chain()
    print(f'Выбрана сеть вывода {chain.name.upper()}!\n')
    amount_input = input_deposit_amount()
    print(f"Сумма хранения каждого кошелька в сети ETHEREUM: {amount_input:.4f} {chain.native_token}!")
    pause = input_pause()
    return chain, amount_input, pause, input_chain

def main():

    if not config.is_browser_run:
        config.is_browser_run = True

    init_logger()
    accounts = get_accounts()

    for i in range(config.cycle):
        accounts_for_work = select_profiles(accounts)
        random.shuffle(accounts_for_work)
        chain, amount_input, pause, input_chain = input_erc_deposit()

        for account in accounts_for_work:
            worker(account, chain, amount_input, input_chain)
            random_sleep(pause)

        logger.success(f'Цикл {i + 1} завершен! Обработано {len(accounts_for_work)} аккаунтов.')
        logger.info(f'Ожидание перед следующим циклом ~{config.pause_between_cycle[1]} секунд.')
        random_sleep(*config.pause_between_cycle)

def worker(account: Account, chain, amount_input, input_chain) -> None:

    onchain_instance = Onchain(account, Chains.ETHEREUM)
    onchain_instance.get_gas_price()
    onchain_instance.gas_price_wait(10)

    try:
        with Bot(account) as bot:
            activity(bot, chain, amount_input, input_chain)
    except Exception as e:
        logger.critical(f"Ошибка при обработке аккаунта {account}: {e}")

def activity(bot: Bot, chain, amount_input, input_chain):

    multiplier = random.uniform(1.01, 1.05)
    amount_input *= multiplier
    onchain_instance = Onchain(bot.account, Chains.ETHEREUM)
    balance_before = onchain_instance.get_balance()
    deposit_amount = amount_input - balance_before

    if balance_before > amount_input:
        logger.warning(
            f'Баланс в сети {Chains.ETHEREUM.name.upper()}: {balance_before.ether:.5f} {chain.native_token}. Пополнение не требуется!')
        return

    withdrawal_chain = Onchain(bot.account, chain)
    chain_balance = withdrawal_chain.get_balance()
    if  chain_balance <= deposit_amount:
        logger.error(f'Баланс в сети {chain.name.upper()} недостаточный для перевода: {chain_balance.ether:.5f} {chain.native_token}!')
        return

    logger.info(
        f'Ожидаемый баланс в сети {Chains.ETHEREUM.name.upper()}: {amount_input:.5f} {chain.native_token}! Пополняем разницу.')
    bot.metamask.auth_metamask()
    bot.metamask.select_chain(chain)
    bot.ads.open_url('https://relay.link/bridge/ethereum')
    time.sleep(5)

    connect_wallet = bot.ads.page.locator('button[aria-label="Connect Wallet"]')
    if connect_wallet.count():
        connect_wallet.click()
        bot.ads.page.locator('img[alt="metamask"]').click()
        metamask_page = bot.ads.catch_page(['notification'])
        if metamask_page:
            metamask_page.wait_for_load_state('load')
            metamask_page.get_by_test_id('confirm-btn').click()

    bot.ads.page.locator('div[id="from-token-section"]').click()
    if input_chain == '1':
        bot.ads.page.locator('div[role="group"]').locator('img[alt="Chain #42161"]').click() # arbitrum
    if input_chain == '2':
        bot.ads.page.locator('div[role="group"]').locator('img[alt="Chain #8453"]').click()  # base
    if input_chain == '3':
        bot.ads.page.locator('div[role="group"]').locator('img[alt="Chain #10"]').click()  # op

    bot.ads.page.locator('div[id="from-token-section"]').locator('svg[aria-hidden="true"]').nth(2).click()
    bot.ads.page.get_by_text('Ether', exact=True).first.click()

    bot.ads.page.locator('div[id="to-token-section"]').locator('svg[aria-hidden="true"]').nth(1).click()
    bot.ads.page.locator('div[role="group"]').locator('img[alt="Chain #1"]').click()

    bot.ads.page.locator('div[id="to-token-section"]').locator('svg[aria-hidden="true"]').nth(2).click()
    bot.ads.page.get_by_text('Ether', exact=True).first.click()

    bot.ads.page.locator('div[id="to-token-section"]').get_by_placeholder('0').click()
    bot.ads.page.keyboard.type(f'{deposit_amount.ether:.5f}', delay=300)
    time.sleep(10)

    if bot.ads.page.locator('div[id="widget-error-well-section"]').is_visible():
        logger.warning(
            f'Сумма вывода слишком маленькая: {deposit_amount:.5f} {chain.native_token}. Транзакция нерентабельная, увеличьте сумму хранения в сети {Chains.ETHEREUM.name.upper()}!')
        raise Exception

    button = bot.ads.page.locator('button[aria-label="Swap"]')
    button_text = button.text_content()

    if button_text and 'Insufficient Balance' in button_text:
        logger.error(f'Баланс в сети {chain.name.upper()} недостаточный для перевода!')
        return

    if button_text and 'Review' in button_text:
        button.click()
        time.sleep(10)
        bot.ads.page.get_by_role("button", name="Swap").click()
        bot.metamask.universal_confirm(windows=2, buttons=2)

    for _ in range(60):
        balance_after = onchain_instance.get_balance()
        if balance_after > balance_before:
            logger.success('Транзакция прошла успешно!')
            break
        random_sleep(10, 15)
    else:
        logger.error('Транзакция не прошла!')
        raise Exception('Транзакция не прошла!')

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.warning('Программа завершена вручную!')