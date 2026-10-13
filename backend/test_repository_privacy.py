from scripts.check_repository_privacy import scan_text


def test_private_values_are_flagged_without_echoing_them():
    private_path = '/Users/' + 'private-person' + '/project'
    credential = 'github_pat_' + 'x' * 35
    findings = scan_text(private_path + '\n' + credential)
    assert findings == [(1, 'personal-path'), (2, 'credential')]
    assert private_path not in str(findings) and credential not in str(findings)


def test_public_examples_and_noreply_addresses_are_allowed():
    example = '/Users/' + 'USER' + '/project'
    email = 'account' + '@users.noreply.github.com'
    assert scan_text(example + '\n' + email) == []
