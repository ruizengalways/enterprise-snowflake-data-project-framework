# Ingestion

Ingestion is source-specific and domain-owned. The Framework does not provide an ingestion runtime.

Create one directory per source system and document:

- source system
- target Bronze objects
- owner
- ingestion method
- replay expectation
- implementation notes

Source directories may contain SQL, connector configuration, Python, Terraform, Openflow, ADF, Fivetran, Snowpipe, Kafka, or other implementation files as needed.
