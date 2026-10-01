# Record browser

Records have unique string IDs and sortable ISO created timestamps.
Browse order is ascending by (created, id). Input order is not significant.
A cursor is an opaque continuation token: the next page starts strictly after the last returned record.
next_cursor is null when no further records remain; clients stop at null.
A lookahead record can detect more results but has not yet been returned.
Offset paging and newest-first feeds are separate APIs with different contracts.
