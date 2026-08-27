with source as (

    select
        raw_payload,
        source_file_name,
        loaded_at
    from {{ source('raw', 'raw_trades') }}

),

renamed as (

    select
        raw_payload:trade_id::string          as trade_id,
        raw_payload:version::number            as version,
        raw_payload:trade_date::date           as trade_date,
        raw_payload:maturity_date::date        as maturity_date,
        raw_payload:counterparty::string       as counterparty,
        raw_payload:instrument_type::string    as instrument_type,
        raw_payload:notional::number(38,2)     as notional,
        raw_payload:currency::string           as currency,
        raw_payload:price::number(38,6)        as price,
        raw_payload:status::string             as status,
        raw_payload:source_system::string      as source_system,
        raw_payload:event_timestamp::timestamp_ntz as event_timestamp,
        source_file_name,
        loaded_at
    from source

)

select * from renamed
