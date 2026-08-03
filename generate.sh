#!/bin/bash

urls=(
    "https://raw.githubusercontent.com/ga4gh-beacon/beacon-v2/refs/heads/main/models/json/beacon-v2-default-model/datasets/defaultSchema.json"
    "https://raw.githubusercontent.com/ga4gh-beacon/beacon-v2/refs/heads/main/models/json/beacon-v2-default-model/genomicVariations/defaultSchema.json"
    "https://raw.githubusercontent.com/ga4gh-beacon/beacon-v2/refs/heads/main/framework/json/responses/beaconInfoResponse.json"
    "https://raw.githubusercontent.com/ga4gh-beacon/beacon-v2/refs/heads/main/framework/json/responses/beaconBooleanResponse.json"
    "https://raw.githubusercontent.com/ga4gh-beacon/beacon-v2/refs/heads/main/framework/json/responses/beaconCountResponse.json"
    "https://raw.githubusercontent.com/ga4gh-beacon/beacon-v2/refs/heads/main/models/json/beacon-v2-default-model/genomicVariations/endpoints.json"
    "https://raw.githubusercontent.com/ga4gh-beacon/beacon-v2/refs/heads/main/framework/json/responses/ga4gh-service-info-1-0-0-schema.json"
    "https://raw.githubusercontent.com/ga4gh-beacon/beacon-v2/refs/heads/main/framework/json/responses/beaconConfigurationResponse.json"
    "https://raw.githubusercontent.com/ga4gh-beacon/beacon-v2/refs/heads/main/framework/json/responses/beaconMapResponse.json"
    "https://raw.githubusercontent.com/ga4gh-beacon/beacon-v2/refs/heads/main/framework/json/responses/beaconEntryTypesResponse.json"
    "https://raw.githubusercontent.com/ga4gh-beacon/beacon-v2/refs/heads/main/framework/json/responses/beaconFilteringTermsResponse.json"
    "https://raw.githubusercontent.com/ga4gh-beacon/beacon-v2/refs/heads/main/framework/json/responses/beaconCollectionsResponse.json"
    "https://raw.githubusercontent.com/ga4gh-beacon/beacon-v2/refs/heads/main/models/json/beacon-v2-default-model/cohorts/defaultSchema.json"
)


outputs=(
    "src/beaconize/models/dataset.py"
    "src/beaconize/models/genvars.py"
    "src/beaconize/models/response_info.py"
    "src/beaconize/models/response_bool.py"
    "src/beaconize/models/response_count.py"
    "src/beaconize/models/endpoint_genvars.py"
    "src/beaconize/models/service_info.py"
    "src/beaconize/models/configuration.py"
    "src/beaconize/models/MapResponse.py"
    "src/beaconize/models/EntryTypesResponse.py"
    "src/beaconize/models/FilteringTermsResponse.py"
    "src/beaconize/models/CollectionsResponse.py"
    "src/beaconize/models/cohort.py"
)

format_urls=(
    "jsonschema"
    "jsonschema"
    "jsonschema"
    "jsonschema"
    "jsonschema"
    "json"
    "jsonschema"
    "jsonschema"
    "jsonschema"
    "jsonschema"
    "jsonschema"
    "jsonschema"
    "jsonschema"
)

for i in "${!urls[@]}"; do
    echo "Processing: ${urls[$i]} -> ${outputs[$i]}"
    uv run datamodel-codegen \
        --url "${urls[$i]}" \
        --input-file-type "${format_urls[$i]}"\
        --output "${outputs[$i]}" \
        --output-model-type pydantic_v2.BaseModel
    
    if [ $? -eq 0 ]; then
        echo "Successfully generated ${outputs[$i]}"
    else
        echo "Error generating ${outputs[$i]}"
    fi
    echo "---"
done

