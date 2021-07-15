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
* ```oral_argument``` -- within the ```case_full``` JSON object, call each ```oral_argument->>href``` (i.e. ```https://api.oyez.org/case_media/oral_argument_audio/22753```) to return any available ```oral_argument``` JSON object(s). There is typically only one object to return per case, but there can be multiple or none available depending on the case.

The [oyez.py](oyez.py) script saves all these JSONs to disk (2.3 GB so far for 60 years worth of data). In [run.sh](run.sh), we use the AWS CLI to sync the data from disk to S3. Then [s3_to_rds.py](s3_to_rds.py), compares the data in RDS against S3 to incrementally load new data to the database. Then, we run some aggregation queries using [rds.py](rds.py) to transform the data for end-user consumption.

The RDS tables keep the full JSON files in ```jsonb``` columns, with the goal of transforming in SQL as needed. In each table, we also track the ID (parsed from the file name), the timestamp of the insert, and the S3 object key.

### Requirements

I'm ignoring the JSON files for this repo, so first run [init.sh](init.sh) to set up the local directories for your own project. This will also attempt to install packages from [requirements.txt](requirements.txt).

On the AWS side, you'll need: 
* [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2-mac.html#cliv2-mac-install-cmd)
* S3 bucket (i.e. `s3://scotustician`)
* Postgres RDS database (run [raw_ddl.sql](raw_ddl.sql) to set up the staging data tables)
* Secrets Manager to encode your RDS credentials so that the `s3_to_rds.py` and `rds.py` scripts can access. In these scripts, also substitute your other relevant RDS information (host URL, database name, port).

Then, use [run.sh](run.sh) to run the whole job.

### Next steps

* Plotly Dash app to visualize data
* Containerization 

## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details