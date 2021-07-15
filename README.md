# SCOTUStician

### Background

Data sourced from www.oyez.org undocumented public API. CC-BY-NC Oyez, Inc.

Oyez.org is an archive of Supreme Court information and media, including transcripts of oral argument sessions. Per Supremecourt.gov:

```
The Court holds oral argument in about 70-80 cases each year. The arguments are an opportunity for the Justices to ask questions directly of the attorneys representing the parties to the case, and for the attorneys to highlight arguments that they view as particularly important.

In these sessions, each side has thirty minutes to present its case aloud. In rare cases, the time limit may be extended. Oral arguments are typically limited to the justices, the counsels for the parties of the cases, and about 50 seats set aside for members of the public to watch. The Court began recording Oral Arguments in October 1955. Beginning in October 2010, the Supreme Court began the practice of posting recordings and transcripts of the oral arguments made during the preceding week on Fridays on the Court's website.
```

### Summary

The data pipeline populates 3 entities with some different API calls:

* ```case_summary``` -- call ```https://api.oyez.org/cases?per_page=0``` to return a JSON array of ```case_summary``` objects. These contain basic metadata about the case but no information about oral arguments, so we need to continue parsing. 
* ```case_full``` -- within the JSON array of ```case_summary``` objects, call each ```href``` (i.e. ```https://api.oyez.org/cases/2000/00-24```) to return a ```case_full``` JSON object with some additional metadata.
* ```oral_argument``` -- with the ```case_full``` JSON object, call each ```oral_argument->>href``` (i.e. ```https://api.oyez.org/case_media/oral_argument_audio/22753```) to return any available ```oral_argument``` JSON object(s). There is typically only one object to return per case, but there can be multiple or none available depending on the case.

The [oyez.py](oyez.py) script saves all these JSONs to disk (2.3 GB so far, for 60 years worth of data). In [run.sh](run.sh), we use the AWS CLI to sync the data in S3. Then our last script, [rds.py](rds.py), compares the data in RDS against S3 to incrementally upload new data. 

The RDS tables keep the full JSON files in ```jsonb``` columns, with the goal of transforming in SQL as needed. In each table, we also track the ID (parsed from the file name), the timestamp of the insert, the S3 object key.

### Requirements

1) [Install AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2-mac.html#cliv2-mac-install-cmd)

2) Install the necessary Python libraries:
```zsh
pip install -r requirements.txt
```

3) Set environment variables for RDS and S3 based on your personal resources:
```zsh
export SCOTUSTICIAN_RDS_HOST=''
export SCOTUSTICIAN_RDS_PORT=''
export SCOTUSTICIAN_RDS_DBNAME=''
export SCOTUSTICIAN_RDS_USERNAME=''
export SCOTUSTICIAN_RDS_PASSWORD=''

export SCOTUSTICIAN_S3_BUCKET=''
```

4) Set up Postgres tables on your RDS (you'll be prompted for your RDS password.):
```zsh
psql --host=$SCOTUSTICIAN_RDS_HOST --port=$SCOTUSTICIAN_RDS_PORT --username=$SCOTUSTICIAN_RDS_USERNAME --password --dbname=$SCOTUSTICIAN_RDS_DBNAME -f ddl.sql
```

5) Run the job:
```zsh
sh run.sh
```

### Next steps

* Write SQL queries to create more consumable datasets from the jsonb "raw" data
* Data visualizations (Plotly Dash)

## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details