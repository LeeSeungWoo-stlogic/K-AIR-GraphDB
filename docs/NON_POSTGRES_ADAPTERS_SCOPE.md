# 이기종 RDB 어댑터 범위 (Step 1 본류와 분리)

`meta_ingest`의 **Step 1 실추출·검증 본류**는 **PostgreSQL** 경로다.

- **Oracle / MySQL / Tibero** 등 어댑터 파일은 **목업·스켈레톤** 수준이며, 운영 이관·추출 로직은 **별도 PM/트랙**에서 확정한다.
- **MongoDB·Heavy DB** 등 비관계형·별도 엔진은 본 Step 1 범위 밖이며 **목업 또는 별도 설계**로 둔다.

구현 우선순위와 계약은 `docs/GUIDE_RDBMS_to_온톨로지_파이프라인.md` 및 `services/meta_ingest_proto/README.md`를 따른다.
