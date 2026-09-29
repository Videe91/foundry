"""Every certification record written before the current record format stays exactly as it was.

The Grok runtime-v1 and runtime-v2 graph records, Astra's schema-refused graph record and both
Slice-1 records were committed at 80ec454 (before schema binding, format v2). Astra's first
semantic graph record (NOT CERTIFIED, 21/24, format v2, exam v1) was committed at 5e88489 (before
exam binding, format v3). Each later binding is prospective: it never rewrites, re-scores or
re-reads an earlier record into a certificate, and it never fabricates an identity into a record
that was written without one.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

from tests.certification._certification_run import EVIDENCE_ROOT
from tests.certification._intent_graph_exam import (
    GRAPH_CERTIFICATION_RECORD_FORMAT,
    HISTORICAL_GRAPH_NAMESPACES,
    SCHEMA_BOUND_RECORD_FORMAT,
    record_format,
)

EVIDENCE_AT_80EC454: Final[dict[str, str]] = {
    "openai/gpt-6-astra/case_a_ledger.json": (
        "afcebdb05e95d1de357adb35b63f954621018da1e0cc4a890804ee23d7232e5c"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_v2/certification.json": (
        "c93642bb82cea5106ed1c275548aca5477f640e689104dae615e2df6d43fbc1e"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_v2/measurements.json": (
        "371e60683a7730b7c63fd728608c34e8d25bace0f08370b354d3828dbab31f8a"
    ),
    "openai/gpt-6-astra/measurements.json": (
        "f159aa3fe77eb8e246299c194b4b6e6cafc3708d88e9e455741cbb8928e78081"
    ),
    "xai/grok-4.7/case_a_ledger.json": (
        "db4b0e495398e4faf8d92b2113b30094dacd7a69e3a66546060cf0d9b47f93b0"
    ),
    "xai/grok-4.7/intent_graph_synthesis/case_a_ledger.json": (
        "0626caf1881c6448681d7f10ba555ccfa1dffd1088fec5cf90f8eba0cf3a2369"
    ),
    "xai/grok-4.7/intent_graph_synthesis/case_b_ledger.json": (
        "43c8e2cfee90fbb7e1a2e68702ad5ecf7ab4af1ce52a1a1b89f96748533356a9"
    ),
    "xai/grok-4.7/intent_graph_synthesis/case_c_ledger.json": (
        "434ae05e50f605073b4d2220df2220d4382a3708af4e53d8dc6bfc1f39cf15ba"
    ),
    "xai/grok-4.7/intent_graph_synthesis/case_d_ledger.json": (
        "139e078eb3aa6cb4e5d6869bbdb6b6723ab77548e264e050d845ecc10b9a33c0"
    ),
    "xai/grok-4.7/intent_graph_synthesis/case_e_ledger.json": (
        "f48a9a3dc0029a02fd5314decac747781c056b980b9f5fb8283bddeb42920526"
    ),
    "xai/grok-4.7/intent_graph_synthesis/case_f_ledger.json": (
        "fa7dee528abb3398a2402c5fd9389acdd5286aee7a046ac9060eac6061e4a59d"
    ),
    "xai/grok-4.7/intent_graph_synthesis/case_g_ledger.json": (
        "6f019ca48b44fb56c0f4bea4f8a635fdd2b1657bf349eec85775b423ac6b21a7"
    ),
    "xai/grok-4.7/intent_graph_synthesis/case_h_ledger.json": (
        "6bfa14a02a40d5ff2068d6fc2b28f341b0ce3e4b3e1e87d8376b77935e2655de"
    ),
    "xai/grok-4.7/intent_graph_synthesis/certification.json": (
        "d1bc0c55b4c15e62c6b54ebe590e0c87c3d79ab31b10de5b2515d3e8fcd40070"
    ),
    "xai/grok-4.7/intent_graph_synthesis/measurements.json": (
        "cf59649ae589c2e1513f911354f447d43517d15dbedf40dd995d248fc2138801"
    ),
    "xai/grok-4.7/intent_graph_synthesis_v2/case_b_ledger.json": (
        "cbff91c484a2e0f9582f2e88b1be909444e373388191bd5b0d8c9d71eb3caba8"
    ),
    "xai/grok-4.7/intent_graph_synthesis_v2/case_c_ledger.json": (
        "72fc6a861b4c66296354e1caeebc755aef396c7b8951652eb481d53e21105d69"
    ),
    "xai/grok-4.7/intent_graph_synthesis_v2/case_d_ledger.json": (
        "fd36ba73eb942c5e9dc4fa4d556d2f3bd79da47d5bc890de30ece9b8c5c2b513"
    ),
    "xai/grok-4.7/intent_graph_synthesis_v2/case_e_ledger.json": (
        "3e3eb8784362361ec21cb6557d41882a29ea9827f3eb57549f20d0cd38084664"
    ),
    "xai/grok-4.7/intent_graph_synthesis_v2/certification.json": (
        "9885131d8cac4e95ee6945dd1142abf4a71e015f15b1c52a11689bff35b92d3e"
    ),
    "xai/grok-4.7/intent_graph_synthesis_v2/measurements.json": (
        "f6c77e382d2cd8717a61bd59c29015bced649204b2307c5048dc4a833a016097"
    ),
    "xai/grok-4.7/measurements.json": (
        "3f1e1080dafa080c6a0e4453fa8ac9a4c9a799b7072950fcef1e5920b6896305"
    ),
}
"""SHA-256 of every committed evidence file at 80ec454, read from the git objects."""

EVIDENCE_AT_5E88489: Final[dict[str, str]] = {
    "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/case_a_ledger.json": (
        "4358799b16ec52c584abd8106c522301b41481fec466c4ae057d883e5612c8fb"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/case_b_ledger.json": (
        "9f8931f7e7820b8d191b7b1bcc5f6d9c9331d2c6d37e00dd6fbbdc15774ce1ed"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/case_c_ledger.json": (
        "37ad3a84d5314d6f2b712b3b751e51c77e93da8bdbbe7087a3760f51be5b8007"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/case_d_ledger.json": (
        "db882c34d632a7a0a2ebaa23ca48be3870d923b9c1d71192ceff3d9c311c9cf3"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/case_e_ledger.json": (
        "141bae4148408e61c350b0132da210974843bb088ea8d0e179796aae72bd400a"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/case_f_ledger.json": (
        "1e6cfb2b1014343bec241837c9ed4b2d38efb40fcf4e8634ff474b7fedf4d9a1"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/case_g_ledger.json": (
        "ab3b9ce183dbd2581405d3f83e69a45e8186e343f75b89a8dd8fcc0be6fe4ca9"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/case_h_ledger.json": (
        "62b84221c97e671fa581180803c634f0ebb598e6823bd18116183a8b292e8bb7"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/certification.json": (
        "e2f53ae6c49ea1b2184faffb070b2e4cf58fbec9d849eb5eb07aad37de6de697"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/measurements.json": (
        "468d7b50d4d45c256304cc00cdf713ccc3e0147194bef0d167ab81430309b433"
    ),
}
"""SHA-256 of Astra's schema-bound, exam-v1 graph evidence at 5e88489, from the git objects."""

EVIDENCE_AT_5FF8EDF: Final[dict[str, str]] = {
    "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/case_a_ledger.json": (
        "85defd235403436cfe1262d18817f2588f8f13270b793cf978e3d3dcf1a84f64"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/case_b_ledger.json": (
        "c2232e634f669a72e7e4b99fdca62095995d22d2691da4d6a82276e9ca1f1d22"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/case_c_ledger.json": (
        "977521a946f59a57f22b08512bf0ccaf480f84c62222fb4874a96041f83c61c4"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/case_d_ledger.json": (
        "effbd5ad088581caecf9cc3111f217f756990356f04861c6394466d633ad2050"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/case_e_ledger.json": (
        "c75bfc80b02b56ba9a5ceb4a32e6f6446eca141a696808a242ae845b1c7cdb2e"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/case_f_ledger.json": (
        "930f1da738dd6085cb3ed53e7cc61585910cd4a260405657421d91b7a9189b4c"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/case_g_ledger.json": (
        "2a810b704a69703d5af004a8edc9aca6c9a4c17ba82bbfce79d3b8307601e07c"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/case_h_ledger.json": (
        "fca0a74747ef84e1ead37535e5f34c66dfd82cde6687ba3cf63f73114c7a6696"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/certification.json": (
        "2d57db6a373a5840a055c97fc4597d251c4a53d122c2c46e55f52f7a9ece3923"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/measurements.json": (
        "0037054493d77deda87c5d5d491835673f5de8fdc23752d878422d5d0784045b"
    ),
}
"""Astra's exam-v2 certificate (PASS 24/24, runtime-v2), committed at 5ff8edf. Superseded."""

GROK_EXAM_V2_DIAGNOSTIC: Final[dict[str, str]] = {
    "xai/grok-4.7/intent_graph_synthesis_exam_bound/case_a_ledger.json": (
        "5c347c539c2e97927d280d4e6f1aae4018ee39e65a5621df438cf102e2fc4f70"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_bound/case_b_ledger.json": (
        "df67f918aee9851c2e6fa07eec945c3777344a43bae20ccd1fd659e4cb1d9eef"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_bound/case_c_ledger.json": (
        "9dd69d20f0609804044e00363fbdfe6ffab97b68bf173877a19592bbaa356803"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_bound/case_d_ledger.json": (
        "be1c0024ea6162fd09efa7a94844b26617cca5904fba236a85d8b1c72217b28f"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_bound/case_e_ledger.json": (
        "0736d50cfd1c4eed0552804b262f1d021bc28ca121f00fa084e4055d100d68c9"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_bound/case_f_ledger.json": (
        "c198710b3b833f759d42d26189902155420619a0ca1f05bde1a8011af54ebb19"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_bound/case_g_ledger.json": (
        "ad3a62b145694ecefe5835e370a48c62ad439764fa9e4a6b7ac0da07d25d4c1c"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_bound/case_h_ledger.json": (
        "9ed3f4fe691bb2514d80e98049647b3e5eb2cbab4bd85af88f9a20b20a2e23d1"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_bound/certification.json": (
        "f0750c8f2b84a23300c29a72d49cacf68824885ab2e7e86be3c74d80195d79f3"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_bound/measurements.json": (
        "a9493b79cacc29d39a3b9d566657d9b39378c2642cb0e2569e3104db2a54f1c0"
    ),
}
"""Grok's exam-v2 run (NOT CERTIFIED 21/24), captured byte for byte before it was committed as
diagnostic evidence: its case A failures fall in the dimension exam v2 left unspecified."""

EVIDENCE_AT_2F9F5D6: Final[dict[str, str]] = {
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/case_a_ledger.json": (
        "111a653c9d0ae6eafb2c9a0483181af166cc807d9490c0d2e979ee9dfef2fffe"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/case_b_ledger.json": (
        "c4116e44e88d214f1eb036223bafb281e20523b426a897d5441610e3cac407f4"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/case_c_ledger.json": (
        "e75286dd0e10f2cebf42a19df8365633af4225742f42f06368fde24c6f623b9f"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/case_d_ledger.json": (
        "de73e613f5d2216c07877eec19d0866272bbeae69f1490b2a6655cf4ef16a79f"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/case_e_ledger.json": (
        "5a50dff148a2a46b2885f4f37d8f7ee6b708e4921a4fc7fc1c63ec573e0daa46"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/case_f_ledger.json": (
        "d620539a82fa27afc311812c19c6ea202ace97a998c37fda710a5c1a564597f7"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/case_g_ledger.json": (
        "f2ad202c4c223c6ff4ea12b8209dc601a0da628225bdbba7e9b83eac88fc02e5"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/case_h_ledger.json": (
        "61c542f07f6e5f7a596b75c5d05b9fe9ced0c1164aea69042c50bcf4a96c797b"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/case_i_ledger.json": (
        "762b7a4e46a5aa6f543d4f26debdcd411a1aa01330ce7b975eed39d5db2758c4"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/certification.json": (
        "6c0480a463a413001f56b21d9fced9fa23950499e9327083c974f082ce698b88"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v3/measurements.json": (
        "35ceb7d92c52017ab153251eaa1f88c3403bf64103b08f4141b94888186596eb"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v3/case_a_ledger.json": (
        "74628d59d1d07f767d09f9de15cd8a1b28e446120af8f73f479b0da2a6a4a983"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v3/case_b_ledger.json": (
        "ab00f37f697f8ccd6bfe1b6ec665d6a35ec593d0d0b21b63548bd72b58a82908"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v3/case_c_ledger.json": (
        "7095ac57e1514b933704aad33b0161af7d337ae9aea7a727a821af19e91e8ad7"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v3/case_d_ledger.json": (
        "b23804ddc2cb8c6b1f2781dba1c4ea3390233bdfd218c590008316c8d63d34b0"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v3/case_e_ledger.json": (
        "c15891a3e0d683663a8beb5e30fccef166db047a3f5ada293bbf6e6c25432cf5"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v3/case_f_ledger.json": (
        "e934b14ed263ccca7e6c4e5f24af0f5541d91364f89e3cef864674f47e7adf78"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v3/case_g_ledger.json": (
        "f9f2d59e4b0fbf7d836edda509cb1558d093d99b1dc7ac5400f8300b2e8b2e2d"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v3/case_h_ledger.json": (
        "92ce7e8b164fdbec9746cab3b605d23cf0a775e6f85826f9b6b9aab4f7fd7927"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v3/certification.json": (
        "1f6e4e41b1ba137e3c8f3f518d55d89bc2ea884e980df92486803e68da13e6d5"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v3/measurements.json": (
        "7b29e655f041ee7db7ab6f1c298e37811f7d09ef31616ec503edd6c41a926e6a"
    ),
}
"""Exam v3 under runtime-v3, committed at 2f9f5d6: Astra PASS 27/27 (now superseded by exam v4)
and Grok NOT CERTIFIED 20/27."""

EVIDENCE_AT_D166938: Final[dict[str, str]] = {
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v4/case_a_ledger.json": (
        "22e81b648fc9d83543baf7b81e6e89653d1f65ffe24da7feca7b3a2fa5200eb1"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v4/case_b_ledger.json": (
        "41f6233b84eb6fac0a3ad31c4a62c9cbd43e4402077f6c55d8ca2e52135d66ba"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v4/case_c_ledger.json": (
        "56e1ed32333715747c1bb3b3a014ab1c4345a7c046af75854362a339f4a3a55f"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v4/case_d_ledger.json": (
        "fee93b5ab1a76f726d9ff42263c616ed58f8ced8c04af20fb1fe24d09867f614"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v4/case_e_ledger.json": (
        "984891114500ed877b7f2af4fa93ea735f71f8c25d227947f78d94c83f100e97"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v4/case_f_ledger.json": (
        "a1bddb17cdd5dfb1cbf25f5742981c495f27f1a343e4711d3c517756f52070c3"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v4/case_g_ledger.json": (
        "beb149beea236342c5569b26ecabc450887b94343ce539ab28d90f8edcfc2815"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v4/case_h_ledger.json": (
        "8d36050111f72283185e15d346c0db10d47048256a2d11e86c7f0276ba61bd83"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v4/case_i_ledger.json": (
        "45dc693a3490b907e973a2b6f41657c60912204f59202095a6ff63ba4f54a76f"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v4/certification.json": (
        "aa381e62e8217c06f2daff88abb6ee35ddd3e3d57623e1f53b7c1e251f74bbe8"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v4/measurements.json": (
        "c661a57cbad7b214cb911409a450275a90d0b6ae417e7e4147680a41b35b75cb"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v4/case_a_ledger.json": (
        "8386ea64e23a4256b8eede812ee6559eac45efe8e830b673ce4894a1f18efab2"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v4/case_b_ledger.json": (
        "fb9c5007588ef64b1652611a5a520924fd2dfaa99401ed9907b91401b24c7bc4"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v4/case_c_ledger.json": (
        "2ec00c07f1f324d1c5951e66fdd31c400cebdea929d4d8b48e46f16eb8fa570e"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v4/case_d_ledger.json": (
        "05001c94750543c6cc3450d477e726daec144be63a1df04e6e9f22d693fe0297"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v4/case_e_ledger.json": (
        "92957fbdc8c1a10473d714c2ad1996e9f177f31713251702a294f983ab4391ae"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v4/case_f_ledger.json": (
        "f563c6aedcee48c47f263d875f2d51bfe8781bc0f0ce8b2e81c6e1e81510ef21"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v4/case_g_ledger.json": (
        "bc1d85d4987ca7aca5478a117ec15a23b2d2f79a9c5f0135a0c783758ad13438"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v4/case_h_ledger.json": (
        "fd96f20201e3060a689f79a7d720d8cc4d48403d332b00dfd798c24170eccbdc"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v4/case_i_ledger.json": (
        "e4f48fe73a5beecc90337cf78fcea8b38dad598ce703d207e2f4f70824b60784"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v4/certification.json": (
        "dde3fb35895462060a7dd62ca53c6853b95558eb8505a5f43d00a902f5896f58"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v4/measurements.json": (
        "e60e160c7d31e8a495dd1db150f4ef0ac1bbd440e8f907d21796f6963044f6dd"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v4/case_a_ledger.json": (
        "e5c9452d016346e20c082a96ee00a7f404b522a49a4bc88e86ee37a6bcf5cda9"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v4/case_b_ledger.json": (
        "4fb6f867f1d17712c5cb38605f69252b9fa761d63a89957df1bed7e134fb4d88"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v4/case_c_ledger.json": (
        "b668bd5ee615771c2eca66f86c8726d9449541bf1cbeed49e8c898af83cf56eb"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v4/case_d_ledger.json": (
        "bea93172aaa3885896febe07a25293fd543583fd826b59123e0d67ddcbe3e961"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v4/case_e_ledger.json": (
        "75d657afbdfe6bdaf5b57085d414e510a585396c5026b324e87eb42da78e1d56"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v4/case_f_ledger.json": (
        "9065a45d8757cd8016a89c8413da0ea2704a85e4ed2f4194fde5ea82705d8bde"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v4/case_g_ledger.json": (
        "437d12107e1e5c24de5c3dbc59cca6e5e2f97b71a369fe411ab5577f621cfc34"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v4/case_h_ledger.json": (
        "af0068702e487b2e0bc021f0960f1ffcda0219623ccd38e541448d632803e833"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v4/case_i_ledger.json": (
        "106e1d3ef25730823e194c23427a1de2cab38a1fc94f8f8cab287a2d9b46b921"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v4/certification.json": (
        "a23a91b75888619c559cb7e6479cbc803c0bc58200105a073d77e0b29339fe30"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v4/measurements.json": (
        "1bf052342450ae76d62350b483f2c24ca95311fff353876eff1d1f2b406c5b1c"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v4/case_a_ledger.json": (
        "cb623b39f5d72789b9d0ee681a349ccc9dc968b47288927d8610516586c9fe05"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v4/case_b_ledger.json": (
        "c4116e44e88d214f1eb036223bafb281e20523b426a897d5441610e3cac407f4"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v4/case_c_ledger.json": (
        "3ae219c252029c4cbb37b82861c5b69855962bad0ddb0413ce3790ee549f0f22"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v4/case_d_ledger.json": (
        "90cd382d904894868d72599b88ca64b8beb42891a7f6a6617cfcb93799ed03a0"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v4/case_e_ledger.json": (
        "0c7e6d0d45e1bc9163d66ea8cbeedc9a2133e61fdf2d3bcc771618c9f391e5de"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v4/case_f_ledger.json": (
        "4ef80af46f21d91f6f903e6dfc04dcf60ee186b9b95ca5ecb0277b8e0b91f402"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v4/case_g_ledger.json": (
        "624e6379baaca2937d73f45119b84f6ab3274f05ebd24dcdcb08a8ec021a0d41"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v4/case_h_ledger.json": (
        "3101c53ed92343d5054800ac43ad754e4c5733902483121a16ea6dec707c6feb"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v4/case_i_ledger.json": (
        "6693b2aafa8bd1f639d0a72cf2bc04efe4953ad793e9a5471ad5a76c75db3bb9"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v4/certification.json": (
        "232fcc90ab1bd3bd60f7d093816b59458fa8169e8c2a00512fb873b3495e2e0e"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v4/measurements.json": (
        "58b50357beb01bf6ea5485090901b6028ba5f046b62103f6e29db3caa09bd019"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v4/case_a_ledger.json": (
        "50393db3ac8a3d8b2e4c84a5a316ad6d7389298e5ef28be6b95493ce2cf5ed23"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v4/case_b_ledger.json": (
        "ab00f37f697f8ccd6bfe1b6ec665d6a35ec593d0d0b21b63548bd72b58a82908"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v4/case_e_ledger.json": (
        "6c1e1dd7969608d6f69de7614feec65689a190486abfb922a254e4557397eef4"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v4/case_f_ledger.json": (
        "09a7d1b887239f69113ab7ee94f1ca841697aaad4cd6b6771d1df8a493122f7b"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v4/case_h_ledger.json": (
        "a52447730f64c848d78bd2452939d45fc21dbb4122d6ab1266f799d5d7bd68f3"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v4/certification.json": (
        "5e6be837a1ae07366c1fc655791244a9f2515b102043972347645c93526e76b6"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v4/measurements.json": (
        "b041c5b1109aa78822f59cf0e541f43405fa76a6dc8a4d473ad132b46f4292fc"
    ),
}
"""Exam v4 under runtime-v3, final at d166938: Astra (d14933e), Claude Opus 5.5 and Claude Sonnet
5 PASS 27/27 (now superseded by exam v5), Claude Fable 5.1 NOT CERTIFIED 23/27 (122a3c2) and
Grok NOT CERTIFIED 17/27 (d14933e; 10 INCOMPLETE, so only 7 files)."""

EVIDENCE_AT_301C474: Final[dict[str, str]] = {
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v5/case_a_ledger.json": (
        "0fc4587c06f12a3222243c0c2e64ec477d2cf8feece1c1c5f076de67b4115552"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v5/case_b_ledger.json": (
        "4397ddf8846a083fdcad55d8b040b21c87d5a14355599b90f6aabdd31afa99d5"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v5/case_c_ledger.json": (
        "e64e6059df95c2834d722f4b6bb500b93ea1141f6ab6c8d3fbc6d35994000ce3"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v5/case_d_ledger.json": (
        "8667638cfb228b18ecc48e3411ed4703111249fb03a8eccb098079cce9628761"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v5/case_e_ledger.json": (
        "8382c43371f27aa67041701b7f8183b954888e0768d42db63b84d44b556258d2"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v5/case_f_ledger.json": (
        "e4a085885474930dc4ef44f352922f35045f2f5313599f007616a82db208c851"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v5/case_g_ledger.json": (
        "44329412143edeaf2a5c192c83a5aa2fa6811e4e524e4de9b1a34dbfb4453ec3"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v5/case_h_ledger.json": (
        "cf376fe4fb5378339440060cb9b9434aaad7840e31659c1341599ba2295c0087"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v5/case_i_ledger.json": (
        "ae3dac549a943173e39efd1b01c7cd07dafddab79da6a52e0315b29db77a356c"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v5/case_j_ledger.json": (
        "eff492cfe35f2ad201487fca499bc59259a49269dbde325dc3da0a60b9e9617b"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v5/certification.json": (
        "e15f3905b4280f995c6fac165d89041f2ea6f7ab8478d412cb834b22d91ad21e"
    ),
    "anthropic/claude-fable-5-1/intent_graph_synthesis_exam_v5/measurements.json": (
        "014bfeef85fc4aa90f532aed65fe3b8993eaabdba01a78f7f62270eac8553989"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v5/case_a_ledger.json": (
        "9ee213865034767b93133772d6ae74b9e1746aeedd4c6faf689237a09385b6c6"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v5/case_b_ledger.json": (
        "2ff7f652cc4b7a53978ac09bd5308dc690c8ed0c3c516716d529340f06380d0d"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v5/case_c_ledger.json": (
        "b0d0eae4f77f80b3e580ffa028b2997383922c4c7089756bfc5b7098050d935d"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v5/case_d_ledger.json": (
        "0e3553b0f47f1ed22189b9a3a022283ce4bc5125300a01f824ce013f2d8d51bc"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v5/case_e_ledger.json": (
        "23ca39aadee7fa43e7681e9abc856dc1e1d22122813fc63ec9d514237516c810"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v5/case_f_ledger.json": (
        "49deb677b06a225ccdd7879d53107605ef6db9d72affd0f2b5b041818d7e3f64"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v5/case_g_ledger.json": (
        "b9fd8a9a1b4d40977eb25d2e5b6ca0cf7b75310b652e6812f2619b12eb9e7aed"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v5/case_h_ledger.json": (
        "4a064c95bb33360951c6963c7c7c77743f93318c5df4650b83da472aea08abb7"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v5/case_i_ledger.json": (
        "d8573992f741ab0384c62b37796d7b53fc70ac3325f8b536f78caa958f441714"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v5/case_j_ledger.json": (
        "b924c8cfa96329cfc512aaeb251c5dfae8071d1a5561b882c496fb6d28d4c7c3"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v5/certification.json": (
        "2d7b809ccf70d0d8a953b0f193a297f784f118e9d198c046d3edb505a473f112"
    ),
    "anthropic/claude-opus-5-5/intent_graph_synthesis_exam_v5/measurements.json": (
        "85900be135acc437c3bca48e6c1fef44b7d635f7898c817467854ebdb4b944e3"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v5/case_a_ledger.json": (
        "ad056fa3b7b776ab46136bad49903710051e902b34416326bc2e386c8a4570f8"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v5/case_b_ledger.json": (
        "945abb367bc425a7f8eb993e995aedb12e027962cb110ec2d4297038613d31b5"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v5/case_c_ledger.json": (
        "3c025d52337ead89dbb0ef79bd14944bc5a9d35d31ff0e6c6350c596134fe95e"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v5/case_d_ledger.json": (
        "3e6020e842c79bc4ee8aa66fd175eb3d89ee0445e624103b7a71430832414e4c"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v5/case_e_ledger.json": (
        "a26711cd624ed671a0441bde71ff735a987ee2ace43fa0617979423cad5c0296"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v5/case_f_ledger.json": (
        "13d4c819951a42c30bc2b746e002320bc5d2283e7ae0618a1505ff8d09a08285"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v5/case_g_ledger.json": (
        "8d08c21dc2766d9ebd50b28ee2ec844e5fe99b78731a4c28d54caeb01a6b2ed9"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v5/case_h_ledger.json": (
        "a270b4280384f21a3f219392de0082b2f4f226d0ca344b382da05cdf385f7111"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v5/case_i_ledger.json": (
        "fab0607eb49ee69f622284a69c46318342864df5d3a9a0b8e8d4855a5c1be2d6"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v5/case_j_ledger.json": (
        "b79da6ef8b14336411a312589d3d23eaa2e799dcb910aa6f38e2b2a5d2ac89ed"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v5/certification.json": (
        "c97c409eff9e4df590c86d2ab3dc9314d71ca7efd1b78c44791d308a61ef3435"
    ),
    "anthropic/claude-sonnet-5/intent_graph_synthesis_exam_v5/measurements.json": (
        "a6303f25e4d50fa0569c22c571051b3f375529464a3a85d5ce89d215979a9721"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v5/case_a_ledger.json": (
        "bcd505ee6a041c4f0963876e42dd662fa794832092b9e75e4651ca3bcb825662"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v5/case_b_ledger.json": (
        "ff8d5a9b9899b19d1bfe69f0339c4e478385e64da8da0df0c243a593aaed7182"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v5/case_c_ledger.json": (
        "6cd3662f5686d7aafa71592047ac8da4c0f7a415d3c7d64f3870be01d3708c1f"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v5/case_d_ledger.json": (
        "a09cc7e4d562b9197b84dedd083d6cdb2addd37329f4334668a501234606fb9d"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v5/case_e_ledger.json": (
        "3aab76652c299c03b0a43f9a053d71f45c487c4bb51397ea1b09e36fd453a42c"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v5/case_f_ledger.json": (
        "d2735b4520d8f4280e8bcbf74a39298346aa24d433996ecefb398686f285b762"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v5/case_g_ledger.json": (
        "2525ce54c0df69d5154253cb1ab5a15d620dc5dabfb9412ee265338ebe042fdc"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v5/case_h_ledger.json": (
        "b2726ebbea3449df60c8809ce42148f6d40f558143fabce4819c20cab0a7696e"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v5/case_i_ledger.json": (
        "aebb54ed94e2438925c1024dfb6d23fe119e6b663ed4f5b68d712ed5d13d559a"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v5/case_j_ledger.json": (
        "848ef9414f3d44a04537ae6256194a6b01e846132c3df8164fe4d177a4f8646a"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v5/certification.json": (
        "bc7b3880c31810fcb321a5fb59bf36740157d0f46a601c73faf451481490f822"
    ),
    "openai/gpt-6-astra/intent_graph_synthesis_exam_v5/measurements.json": (
        "c57710d2e8f4a50b44a71f3468376c8fc9fe273eb123fd8c4ccd695d41fb88da"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v5/case_a_ledger.json": (
        "832c877003ae51b8ef59a0bd772d9b504c0100db753622c9b2ccb2aca8e2ea1b"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v5/case_b_ledger.json": (
        "ed1c547d6f28499625fc02958cb2a8dbca89c55fc18cd4039d6415311c5a380f"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v5/case_c_ledger.json": (
        "b9067dc4739ae943bb7bf15d3e84fa28d36661ddf8f0e178c950c1ec2f25fa8d"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v5/case_d_ledger.json": (
        "0601fd91bb589c643bd7d45e7272d590b7066d6706fdfca65702e65c1e3a8191"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v5/case_e_ledger.json": (
        "8e927d399045517c6495226bbb07a43df379eb058ad8a666a1265356eefb19e5"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v5/case_f_ledger.json": (
        "e1b9d1db4bc61e7f20a75dfa542b1201419344f98f8845e7a7ef5495ecd139a5"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v5/case_g_ledger.json": (
        "18163d64b120db80ed1fc07f3a0f232dbe58b98582eae48995ac75dff6820e92"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v5/case_h_ledger.json": (
        "cfc7bf942d6efa24f9f2a23ec955bfe5de670e62c071fc65e29b04d6b1ef364a"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v5/case_i_ledger.json": (
        "af49548468df0bf8f9acfaf94f5dd81022a7ebd8bf08836168edc96dd249b277"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v5/case_j_ledger.json": (
        "42f389bd06da8bf9ae0c86e82142b68f63e5fa70f1f0210b1cc27a8898ebafd4"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v5/certification.json": (
        "d0a42fdc3bb7853e3054ac21984cd9377f2c80cf3eab70b9b0776da891b0d30d"
    ),
    "xai/grok-4.7/intent_graph_synthesis_exam_v5/measurements.json": (
        "78bb5d81d3572f75019f53807d803c1d8ddd51197b4e01f6107c3eae3acc762b"
    ),
}
"""Exam v5 under runtime-v4, final at 301c474: Astra, Claude Opus 5.5, Claude Sonnet 5 and Claude
Fable 5.1 PASS 30/30 and Grok NOT CERTIFIED 29/30, 12 files each. Every v5 PASS is superseded by
exam v6 (root-Intent lifecycle); no v5 verdict is wrong about exam v5."""

PRE_EXAM_BINDING: Final[dict[str, str]] = {**EVIDENCE_AT_80EC454, **EVIDENCE_AT_5E88489}
HISTORICAL_EVIDENCE: Final[dict[str, str]] = {
    **PRE_EXAM_BINDING,
    **EVIDENCE_AT_5FF8EDF,
    **GROK_EXAM_V2_DIAGNOSTIC,
    **EVIDENCE_AT_2F9F5D6,
    **EVIDENCE_AT_D166938,
    **EVIDENCE_AT_301C474,
}

SCHEMA_FIELDS = ("canonical_schema_sha256", "wire_schema_sha256", "wire_schema_compiler")
EXAM_FIELDS = ("exam_id", "exam_version", "exam_sha256")
SCHEMA_BOUND_ASTRA = "openai/gpt-6-astra/intent_graph_synthesis_schema_bound/certification.json"


def test_every_historical_evidence_file_is_byte_identical() -> None:
    assert len(EVIDENCE_AT_5E88489) == len(EVIDENCE_AT_5FF8EDF) == 10
    assert len(GROK_EXAM_V2_DIAGNOSTIC) == 10
    assert len(EVIDENCE_AT_2F9F5D6) == 21  # Astra 11 (with case I), Grok 10 (I-1 had no answer)
    assert len(EVIDENCE_AT_D166938) == 51  # Astra, Opus, Sonnet, Fable 11 each; Grok 7
    assert len(EVIDENCE_AT_301C474) == 60  # Astra, Opus, Sonnet, Fable, Grok 12 each
    for relative, digest in HISTORICAL_EVIDENCE.items():
        data = (EVIDENCE_ROOT / relative).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, relative


def test_no_file_was_added_to_a_historical_namespace() -> None:
    for namespace in HISTORICAL_GRAPH_NAMESPACES:
        for directory in EVIDENCE_ROOT.glob(f"*/*/{namespace}"):
            for path in directory.iterdir():
                assert str(path.relative_to(EVIDENCE_ROOT)) in HISTORICAL_EVIDENCE, path


def test_no_historical_graph_record_gains_an_identity_it_was_not_written_with() -> None:
    records = [r for r in PRE_EXAM_BINDING if r.endswith("certification.json")]
    assert len(records) == 4
    for relative in records:
        record = json.loads((EVIDENCE_ROOT / relative).read_text())
        assert record_format(record) != GRAPH_CERTIFICATION_RECORD_FORMAT
        assert not set(EXAM_FIELDS) & record.keys(), relative
        assert record["verdict"] == "NOT CERTIFIED", relative
        if relative == SCHEMA_BOUND_ASTRA:
            assert record_format(record) == SCHEMA_BOUND_RECORD_FORMAT
            assert set(SCHEMA_FIELDS) <= record.keys()
        else:
            assert record_format(record) == "ie3-graph-certification.v1"
            assert not set(SCHEMA_FIELDS) & record.keys(), relative


def test_the_exam_v2_records_stay_bound_to_exam_v2() -> None:
    """Both were written in the exam-bound format against exam v2 and runtime-v2. Unchanged."""
    expected = {
        "openai/gpt-6-astra/intent_graph_synthesis_exam_bound/certification.json": ("PASS", 24),
        "xai/grok-4.7/intent_graph_synthesis_exam_bound/certification.json": ("NOT CERTIFIED", 21),
    }
    for relative, (verdict, passed) in expected.items():
        record = json.loads((EVIDENCE_ROOT / relative).read_text())
        assert record_format(record) == GRAPH_CERTIFICATION_RECORD_FORMAT
        assert (record["exam_version"], record["exam_sha256"]) == (
            "2",
            "813f04d4605783731bcb8470d0f480caed65a11629e7e501496d86438c26045c",
        )
        assert record["policy_version"] == "intent-graph-synthesis-runtime-v2"
        assert (record["verdict"], record["passed_attempts"], record["required_attempts"]) == (
            verdict,
            passed,
            24,
        )


def test_the_historical_verdicts_are_unchanged() -> None:
    def verdict(relative: str) -> tuple[str, int, int]:
        record = json.loads((EVIDENCE_ROOT / relative).read_text())
        return record["verdict"], record["passed_attempts"], record["required_attempts"]

    assert verdict("xai/grok-4.7/intent_graph_synthesis/certification.json") == (
        "NOT CERTIFIED",
        4,
        24,
    )
    assert verdict("xai/grok-4.7/intent_graph_synthesis_v2/certification.json") == (
        "NOT CERTIFIED",
        7,
        24,
    )
    assert verdict("openai/gpt-6-astra/intent_graph_synthesis_v2/certification.json") == (
        "NOT CERTIFIED",
        0,
        24,
    )
    assert verdict(SCHEMA_BOUND_ASTRA) == ("NOT CERTIFIED", 21, 24)


def test_the_exam_v1_record_keeps_its_three_case_c_failures() -> None:
    """Truthful history under the defective exam: nothing re-scored, nothing credited."""
    record = json.loads((EVIDENCE_ROOT / SCHEMA_BOUND_ASTRA).read_text())
    failed = [(a["case"], a["attempt"]) for a in record["attempts"] if a["verdict"] != "PASS"]
    assert failed == [("C", 1), ("C", 2), ("C", 3)]


def test_the_astra_graph_record_still_means_no_model_examination_occurred() -> None:
    """0/24 is not a semantic score: every attempt was refused before inference."""
    record = json.loads(
        (
            EVIDENCE_ROOT / "openai/gpt-6-astra/intent_graph_synthesis_v2/certification.json"
        ).read_text()
    )
    attempts = record["attempts"]
    assert len(attempts) == 24
    for attempt in attempts:
        assert attempt["verdict"] == "INCOMPLETE"
        assert attempt["outcome"] == "NO_ANSWER"
        assert attempt["failure"].startswith("TransportFailure:")
        assert attempt["output_tokens"] is None
    assert not list(
        (EVIDENCE_ROOT / "openai/gpt-6-astra/intent_graph_synthesis_v2").glob("case_*_ledger.json")
    ), "no answer existed, so no model-authored ledger may exist"
