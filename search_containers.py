#/usr/bin/python3
#~/anaconda3/bin/python

import requests
import csv
import json
import logging
import time
import subprocess
import os
import sys
from tqdm import tqdm

#TODO: Implement asyncio, add config file


def keeptime(start):
    elapsedtime = time.time() - start
    m, s = divmod(elapsedtime, 60)
    h, m = divmod(m, 60)
    logging.debug('Total time elapsed: ' + '%d:%02d:%02d' % (h, m, s) + '\n')

def open_outfile(filepath):
    if sys.platform == "win32":
        os.startfile(filepath)
    else:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.call([opener, filepath])

def error_log():
    if sys.platform == "win32":
        logger = '\\Windows\\Temp\\error_log.log'
    else:
        logger = '/tmp/error_log.log'
    logging.basicConfig(filename=logger, level=logging.DEBUG,
                        format='%(asctime)s %(levelname)s %(name)s %(message)s')
    return logger

def login():
    try:
        url = input('Please enter the ArchivesSpace API URL: ')
        username = input('Please enter your username: ')
        password = input('Please enter your password: ')
        auth = requests.post(url+'/users/'+username+'/login?password='+password).json()
        #if session object is returned then login was successful; if not it failed.
        if 'session' in auth:
            session = auth["session"]
            h = {'X-ArchivesSpace-Session':session, 'Content_Type': 'application/json'}
            print('\nLogin successful!\n')
            logging.debug('Success!')
            return (url, h)
        else:
            print('\nLogin failed! Check credentials and try again\n')
            logging.debug('Login failed')
            logging.debug(auth.get('error'))
            u, heads = login()
            return u, heads
    except:
        print('\nLogin failed! Check credentials and try again!\n')
        logging.exception('Error: ')
        u, heads = login()
        return u, heads

#Open a CSV in reader mode
#CHANGE THIS TO JUST BE A LIST...
def opencsv():
    try:
        input_csv = input('Please enter path to CSV: ')
        file = open(input_csv, 'r', encoding='utf-8')
        #I want this as a list not a generator since it's relatively
        #small and need the length for the tqdm counter
        csvlist = [[barcode.strip()] for barcode in file.readlines() if 'barcode' not in barcode]
        return (input_csv, csvlist)
    except:
        logging.exception('Error: ')
        logging.debug('Trying again...')
        print('\nCSV not found. Please try again.\n')
        i, c = opencsv()
        return (i, c)

#Open a CSV file in writer mode
def opencsvout(infilename):
    try:
        output_csv = infilename[:-4] + '_outfile.csv'
        fileob = open(output_csv, 'a', encoding='utf-8', newline='')
        csvout = csv.writer(fileob)
        return (output_csv, fileob, csvout)
    except:
        logging.exception('Error: ')
        print('\nError creating outfile. Please try again.\n')
        i, f, c = opencsvout()
        return (i, f, c)

def search_voyager_helper(item_data, voyager_url, get_bib_item_ep, barcode):
    try:
        bib_id = item_data['bibid']
        call_number = item_data['callno']
        location = item_data['locname']
        if 'itemenum' in item_data:
            #would want to split this eventually, assuing that 
            box_num = item_data['itemenum']
            series = 'see container_number field'
            cp = 'see container_number field'
        else:
            box_num = 'no_box_number'
            series = 'no_series'
            cp = 'no_container_profile'
        #there should not be more than one result here, for sure...
        search_bib_item = requests.get(voyager_url + get_bib_item_ep + bib_id).json()
        #is this good? Any time this wouldn't work?
        title = search_bib_item['record'][0]['title']
        return [barcode, series, call_number, box_num, title, cp, location]
    # do better
    except Exception:
        logging.exception('Error: ')
        #should this return something?

def search_voyager(barcode, voyager_url, get_item_ep, get_bib_item_ep):
    search_item = requests.get(voyager_url + get_item_ep + barcode).json()
    if search_item == {'items': [{'barcode': 'NA'}]}:
        return [barcode, 'No results found in AS or Voyager']
    else:
        #this assumes that there is only one result for the barcode - which should be the case, I think...
        if len(search_item['items']) == 1:
            item_data = search_item['items'][0]
            return search_voyager_helper(item_data, voyager_url, get_bib_item_ep, barcode)
        else:
            for i, item in enumerate(search_item['items']):
                if item['barcode'] == barcode:
                    item_data = search_item['items'][i]
                    return search_voyager_helper(item_data, voyager_url, get_bib_item_ep, barcode)

def as_search_processing(barcode, search):
    #Searching identifier and title, which are both required fields
    identifier = search['response']['docs'][0]['collection_identifier_stored_u_sstr'][0]
    title = search['response']['docs'][0]['collection_display_string_u_sstr'][0]
    #Checking for a series
    if 'series_identifier_stored_u_sstr' in search['response']['docs'][0]:
        series = search['response']['docs'][0]['series_identifier_stored_u_sstr'][0]
    else:
        series = 'no_series'
        #logging.debug('No series. ' + str(search['response']['docs'][0]))
    #Checking for container info
    record_json = json.loads(search['response']['docs'][0]['json'])
    #Indicator is a required field
    container_number = record_json['indicator']
    #Checking for a container profile
    if 'container_profile_display_string_u_sstr' in search['response']['docs'][0]:
        container_profile = search['response']['docs'][0]['container_profile_display_string_u_sstr'][0]
    else:
        container_profile = 'no_container_profile'
        #logging.debug('No container profile. ' + str(search['response']['docs'][0]))
    #Writing everything to the output CSV
    if 'location_display_string_u_sstr' in search['response']['docs'][0]:
        location_title = search['response']['docs'][0]['location_display_string_u_sstr'][0]
    else:
        location_title = 'no_location'
    return [barcode, series, identifier, container_number, title, container_profile, location_title]

def search_barcodes(csvfile, csvoutfile, api_url, headers, voyager_url, get_item_ep, get_bib_item_ep):
    for row in tqdm(csvfile):
        barcode = row[0]
        try:
            logging.debug('Searching ' + barcode)
            search = requests.get(api_url + '/repositories/12/top_containers/search?q=barcode_u_sstr:' +  barcode, headers=headers).json()
            if search['response']['numFound'] != 0:
                newrow = as_search_processing(barcode, search)
                csvoutfile.writerow(newrow)
            #elif here, or is this ok? Don't want to 
            else:
                voyager_results = search_voyager(barcode, voyager_url, get_item_ep, get_bib_item_ep)
                csvoutfile.writerow(voyager_results)
        #do better
        except Exception:
            #print('Error! Could not retrieve record ' + str(row))
            logging.exception('Error: ')
            #logging.debug(str(search))
            row.append('ERROR')
            csvoutfile.writerow(row)
    #print("\n\nCredit: program icon was made by http://www.freepik.com on https://www.flaticon.com/ and is licensed by Creative Commons BY 3.0 (CC 3.0 BY")

def main():
    print('''\n\n
             #################################################
             #################################################
             ####################  HELLO!  ###################
             #################################################
             #####  WELCOME TO THE LSF TRANSFER BARCODE  #####
             #####               LOOKUP TOOL!            #####
             #################################################
             #################################################
             \n\n''')
    time.sleep(1)
    print("                            Let's get started!\n\n")
    time.sleep(1)
    barcode_logfile = error_log()
    starttime = time.time()
    logging.debug('Connecting to ArchivesSpace API...')
    api_url, headers = login()
    #logging.debug('Opening barcode file...')
    ininput_string, csvfile = opencsv()
    #logging.debug('Opening output file...')
    input_string, fileobject, csvoutfile = opencsvout(ininput_string)
    csv_headers = ['barcode', 'series', 'identifier', 'container_number', 'title', 'container_profile', 'location']
    csvoutfile.writerow(csv_headers)
    voy_api_url = 'http://libapp.library.yale.edu/VoySearch/'
    get_item = 'GetItem?barcode='
    get_bib_item = 'GetBibItem?bibid='
    print('\nPlease wait a moment...\n')
    search_barcodes(csvfile, csvoutfile, api_url, headers, voy_api_url, get_item, get_bib_item)
    fileobject.close()
    keeptime(starttime)
    logging.debug('All Done!')
    print('\nAll Done!')
    open_outfile(input_string)
    open_outfile(barcode_logfile)

if __name__ == "__main__":
    main()
