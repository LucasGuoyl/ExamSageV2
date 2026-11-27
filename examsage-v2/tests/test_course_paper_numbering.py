from test_numbered_source_pages import course, ask


def test_numbered_question_retains_nested_locations_and_ends_before_next_page(tmp_path):
    paper=('SECTION A\n1. Describe the climate.\n2. Figure 1 shows four locations:\n'
           '    1. West coast,\n    2. East coast.\n    i) Describe the curves.\n'
           '    ii) Explain the trend.\n(23 marks)\f— 3 —\n3. Other question.')
    tools,cid=course(tmp_path,paper=paper)
    for query in ['2025 Q2(ii) 只给题目','2025 Q2 只给题目']:
        r=ask(tools,cid,query)
        assert r['sufficiency']=='unassessed' and [x['refs'][0]['page'] for x in r['records']]==[1]
        assert all(s in r['records'][0]['text'] for s in ['Figure 1','West coast','East coast','Explain','23 marks'])
        assert 'Other question' not in r['records'][0]['text']


def test_root_and_first_child_on_same_line(tmp_path):
    tools,cid=course(tmp_path,paper='1. (i) Explain the isotope.\n    (ii) Find the age.\n2. (i) Neighbor question.')
    for query in ['2025 Q1(ii) 只给题目','2025 Q1 只给题目']:
        r=ask(tools,cid,query)
        assert r['records'] and 'isotope' in r['records'][0]['text'] and 'Find the age' in r['records'][0]['text']
        assert 'Neighbor' not in r['records'][0]['text']


def test_whole_question_includes_descendants_and_list_is_part_of_the_stem(tmp_path):
    paper=('1. The sea-level data include:\n    a) eclipse records,\n    b) Roman fish tanks, and\n'
           '    c) coral records.\nDescribe two datasets.\n2. Which effects?\n'
           '    i) Find trends.\n    ii) Which panel shows:\n        a) heat?\n        b) mass?\nExplain why.\n3. Another question.')
    tools,cid=course(tmp_path,paper=paper)
    whole=ask(tools,cid,'2025 Q1 只给题目')
    assert whole['records'] and 'Describe two datasets' in whole['records'][0]['text']
    assert not ask(tools,cid,'2025 Q1(b) 只给题目')['records']
    parent=ask(tools,cid,'2025 Q2(ii) 只给题目')
    assert 'b) mass?' in parent['records'][0]['text'] and 'Explain why' in parent['records'][0]['text']
    assert 'Another question' not in parent['records'][0]['text']


def test_a_partially_readable_root_does_not_become_a_complete_question(tmp_path):
    tools,cid=course(tmp_path,paper='1. Conditions.\na) First.\f\fb) Second.\n2. Other.')
    r=ask(tools,cid,'2025 Q1 只给题目')
    assert r['sufficiency']=='insufficient' and not r['records']


def test_ambiguous_inline_parts_on_next_root_do_not_hide_previous_root(tmp_path):
    paper='1. Derive the equation.\n(6 marks)\n2. Sketch the modes (a) 0S0 and\n(b) 0S2.\n3. Another task.'
    tools,cid=course(tmp_path,paper=paper)
    r=ask(tools,cid,'2025 Q1 只给题目')
    assert [x['text'] for x in r['records']]==['1. Derive the equation.\n(6 marks)']
    assert not ask(tools,cid,'2025 Q2(b) 只给题目')['records']


def test_unknown_and_multiple_question_references_do_not_select_one(tmp_path):
    tools,cid=course(tmp_path,paper='1. First question.\n2. Next.')
    for label in ['Q1/2','Q1 and 2','Q1[VII]','Q1xylophone','Q1、2']:
        assert not ask(tools,cid,'2025 '+label+' 只给题目')['records'],label


def test_first_inline_child_preserves_its_nested_children(tmp_path):
    tools,cid=course(tmp_path,paper='1. (a) Family\n        (i) One.\n        (ii) Two.\n    (b) Other.\n2. Last.')
    r=ask(tools,cid,'2025 Q1(a)(ii) 只给题目')
    assert r['records'] and 'Two.' in r['records'][0]['text'] and 'Other.' not in r['records'][0]['text']
    assert not ask(tools,cid,'2025 Q1(ii) 只给题目')['records']


def test_inline_numeric_neighbor_and_numbered_cover_instructions(tmp_path):
    tools,cid=course(tmp_path,paper='Candidate instructions:\n1. Show all working.\n2. State units.\n3. Return all papers.\fSECTION A\n1. Find the angle.   2. Give the next value.\n4. Calculate 2.5 meters.')
    for label in ('Q1','Q2','Q3'):
        assert not ask(tools,cid,'2025 '+label+' 只给题目')['records']
    assert '2.5 meters' in ask(tools,cid,'2025 Q4 只给题目')['records'][0]['text']


def test_wrapped_list_and_nested_steps_are_part_of_one_question(tmp_path):
    tools,cid=course(tmp_path,paper='1. Choose from the following, including:\n    a) first,\n    b) second dataset, which\n    continues on the next line,\n    c) third option.\nDescribe two.\n2. Follow these steps.\n    1. Balance forces.\n    2. Integrate.\nThen calculate velocity.\n3. Last.')
    assert not ask(tools,cid,'2025 Q1(c) 只给题目')['records']
    r=ask(tools,cid,'2025 Q2 只给题目')
    assert r['records'] and 'Then calculate velocity.' in r['records'][0]['text']


def test_examples_and_cover_instructions_can_continue_across_a_page_turn(tmp_path):
    paper=('Candidate instructions:\n1. Bring a pen.\f— 2 —\n2. No calculator.\n3. Return papers.\fSECTION A\n'
           '1. Consider datasets including:\n    a) shells,\n    b) fish tanks,\nPAPER CONTINUES ON NEXT PAGE\f'
           '— 4 —\n    c) tree rings.\nDescribe two datasets.\n2. Last.')
    tools,cid=course(tmp_path,paper=paper)
    for label in ['Q1(c)','Q3']:
        assert not ask(tools,cid,'2025 '+label+' 只给题目')['records']
    r=ask(tools,cid,'2025 Q1 只给题目')
    assert [x['refs'][0]['page'] for x in r['records']]==[3,4]
    assert 'Describe two datasets' in r['records'][-1]['text']
