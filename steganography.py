from math import sqrt, floor
import numpy as np
import requests
from random import random
from time import sleep
from datetime import datetime
import threading

from creds import ACCOUNTS


IS_TESTING = False

TARGET_TEXT = "Hello world! https://www.youtube.com/watch?v=dQw4w9WgXcQ"

GET_FLAG_URL = 'https://api-flag.fouloscopie.com/flag'
FOULOSCOPIE_LOGIN_URL = 'https://api.fouloscopie.com/auth/login'
GET_USER_INFO_URL = 'https://admin.fouloscopie.com/users/me'
UPDATE_PIXEL_URL = 'https://api-flag.fouloscopie.com/pixel'
GET_FLAG_UPDATES_URL = 'https://api-flag.fouloscopie.com/flag/after'


def get_pixels_with_id():
    flag_data = requests.get(GET_FLAG_URL).json()
    return (
        list(map(lambda datum: (datum['hexColor']), flag_data)),
        list(map(lambda datum: (datum['entityId']), flag_data)))


def get_diag(pixels):
    return floor(sqrt(len(pixels) / 2)) + 1


def hex_to_pixel(hex_value):
    try:
        return np.array([
            int(hex_value[1:3], 16),
            int(hex_value[3:5], 16),
            int(hex_value[5:7], 16),
        ])
    except:
        if hex_value != None:
            print(f'Error parsing hexadecimal value {hex_value}.')
        return np.zeros((3))


def pixel_to_hex(rgb):
    return '#{:2x}{:2x}{:2x}'.format(*rgb).replace(' ', '0').upper()


def get_token(email, password):
    login_response = requests.post(
        FOULOSCOPIE_LOGIN_URL,
        json={'email': email, 'password': password}).json()
    access_token = login_response['access_token']

    user_response = requests.get(
        GET_USER_INFO_URL,
        headers={'Authorization': f'Bearer {access_token}'}).json()
    fouloscopie_token = user_response['data']['token']
    return fouloscopie_token


def update_pixel(pixel_id, color, fouloscopie_token):
    while True:
        response = requests.put(
            UPDATE_PIXEL_URL,
            json={'hexColor': color, 'pixelId': pixel_id},
            headers={'Authorization': fouloscopie_token})
        content = response.json()
        status_code = response.status_code

        if status_code == 200:
            return
        if status_code == 429:
            time_to_wait = content['retryAfter'] / 1000 + 10 * random()
            print('Too short! Next try in {0:.2f}s'.format(time_to_wait))
            sleep(time_to_wait)


def get_index_or_none(list, index):
    if index < len(list):
        return list[index]
    return None


def get_full_flag_with_id():
    pixels, pixels_id = get_pixels_with_id()

    totalDiag = get_diag(pixels)
    full_flag = np.zeros((2 * totalDiag, totalDiag, 3), dtype=np.uint8)
    full_flag_pixel_ids = np.zeros((2 * totalDiag, totalDiag), dtype=object)

    def add_pixel_to_flag(x, y, current_pix):
        full_flag[x, y] = hex_to_pixel(get_index_or_none(pixels, current_pix))
        full_flag_pixel_ids[x, y] = get_index_or_none(pixels_id, current_pix)

    add_pixel_to_flag(0, 0, 0)
    add_pixel_to_flag(1, 0, 1)
    currentPix = 2

    for diag in range(1, totalDiag):
        for x in range(2 * diag):
            add_pixel_to_flag(x, diag, currentPix)
            currentPix += 1

        for y in range(diag + 1):
            add_pixel_to_flag(2 * diag, y, currentPix)
            currentPix += 1

        for y in range(diag + 1):
            add_pixel_to_flag(2 * diag + 1, y, currentPix)
            currentPix += 1

    return np.transpose(full_flag, (1, 0, 2)), np.transpose(full_flag_pixel_ids, (1, 0))


def get_last_updates(last_update_ts):
    return requests.get(
        f'{GET_FLAG_UPDATES_URL}/{last_update_ts}').json()


def get_datetime():
    return datetime.utcnow().isoformat()[:-3] + 'Z'


def bits_to_octet(bits):
    octet = 0
    for bit in bits:
        octet = 2 * octet + bit
    return octet


def get_text_from_flag(full_flag, limit=None):
    bits = (full_flag % 2).flatten()
    if limit != None:
        bits = bits[:limit * 8]
    octets = map(bits_to_octet, np.split(bits, len(bits) / 8))
    chars = map(lambda octet: chr(octet), octets)
    return ''.join(chars)


def char_to_bits(c):
    return list(map(int, '{:8b}'.format(ord(c)).replace(' ', '0')))


def text_to_bits(text):
    return [bit for bits in map(char_to_bits, text) for bit in bits]


def vary_color(color):
    if color == 255:
        return 254
    return color + 1


def get_pixels_to_update_from_flag(full_flag, full_flag_pixel_ids):
    pixel_length = (len(TARGET_TEXT) * 8) + (3 - (len(TARGET_TEXT) * 8) % 3)

    full_flag_flatten = full_flag.flatten()
    full_flag_pixel_ids_flatten = full_flag_pixel_ids.flatten()
    target_text_bits = text_to_bits(TARGET_TEXT)
    while len(target_text_bits) < pixel_length:
        target_text_bits.append(None)

    pixels_to_update = []
    for i in range(0, pixel_length, 3):
        updated = False
        new_color = []
        for j in range(3):
            if target_text_bits[i+j] != (full_flag_flatten[i+j] % 2):
                new_color.append(vary_color(full_flag_flatten[i+j]))
                updated = True
            else:
                new_color.append(full_flag_flatten[i+j])
        if updated:
            pixels_to_update.append({
                'id': full_flag_pixel_ids_flatten[i // 3],
                'color': pixel_to_hex(new_color)})

    return pixels_to_update


def update_pixels_to_update(pixels_to_update, new_pixels_to_update):
    while len(pixels_to_update) != 0:
        pixels_to_update.pop()
    while len(new_pixels_to_update) != 0:
        pixels_to_update.append(new_pixels_to_update.pop())
    return


pixels_to_change_sem = threading.Semaphore()


def compute_change_thread_function(pixels_to_update):
    print('[COMPUTE CHANGE] Starting thread')

    full_flag, full_flag_pixel_ids = get_full_flag_with_id()

    last_update_ts = get_datetime()
    while True:
        print(
            f'[COMPUTE CHANGE] Current text: {get_text_from_flag(full_flag, len(TARGET_TEXT))}')

        new_pixels_to_update = get_pixels_to_update_from_flag(
            full_flag, full_flag_pixel_ids)

        pixels_to_change_sem.acquire()
        update_pixels_to_update(pixels_to_update, new_pixels_to_update)
        pixels_to_change_sem.release()

        print(f'[COMPUTE CHANGE] {len(pixels_to_update)} pixel(s) remaining')

        sleep(30)

        last_updates = get_last_updates(last_update_ts)
        for update in last_updates:
            pixel_id = update['entityId']
            new_color = update['hexColor']
            flag_index = update['indexInFlag']

            where_result = np.where(full_flag_pixel_ids == pixel_id)
            if len(where_result[0]) == 0:
                print('[COMPUTE CHANGE] Pixel outside initial flag', flag_index)
                continue

            coords = (where_result[0][0], where_result[1][0])
            full_flag[coords] = hex_to_pixel(new_color)

        print(f'[COMPUTE CHANGE] Updated {len(last_updates)} pixels.')
        last_update_ts = get_datetime()


def main_thread_function(pixels_to_change, index):
    print(f'[MAIN {index}] Starting thread')

    account = ACCOUNTS[index]
    token = get_token(account['email'], account['password'])
    time_to_wait = 0

    while True:
        sleep(time_to_wait)

        pixel_to_change = None
        pixels_to_change_sem.acquire()
        if len(pixels_to_change) > 0:
            pixel_to_change = pixels_to_change.pop()
        pixels_to_change_sem.release()

        if pixel_to_change != None:
            update_pixel(pixel_to_change['id'],
                         pixel_to_change['color'], token)
            time_to_wait = 120 + 30 * random()
            print('[MAIN {}] Updated {} to {}'.format(
                index, pixel_to_change['id'], pixel_to_change['color']))
            print('[MAIN {}] Next execution in {:.2f}s'.format(
                index, time_to_wait))
        else:
            time_to_wait = 30
            print('[MAIN {}] Nothing to do, waiting 30s'.format(index))


if __name__ == '__main__':
    pixels_to_change = []

    main_threads = []

    for index, account in enumerate(ACCOUNTS):
        new_main_thread = threading.Thread(
            target=main_thread_function,
            args=(pixels_to_change, index),
            daemon=True
        )
        main_threads.append(new_main_thread)

    compute_change_thread = threading.Thread(
        target=compute_change_thread_function,
        args=(pixels_to_change, ),
        daemon=True
    )

    for main_thread in main_threads:
        main_thread.start()
    compute_change_thread.start()

    for main_thread in main_threads:
        main_thread.join()
    compute_change_thread.join()
